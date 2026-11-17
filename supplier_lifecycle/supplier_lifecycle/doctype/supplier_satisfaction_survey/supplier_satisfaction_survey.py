# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from supplier_lifecycle.supplier_lifecycle.permissions import get_supplier_portal_suppliers, is_internal_user
from supplier_lifecycle.supplier_lifecycle.supplier_creation import (
	get_kyc_supplier_contact,
	resolve_supplier_lifecycle_company_name,
	send_supplier_lifecycle_email,
)
from supplier_lifecycle.supplier_lifecycle.db_errors import reraise_if_db_lock_error

DEFAULT_SATISFACTION_SURVEY_CREATED_EMAIL_TEMPLATE = "Supplier Satisfaction Survey Created"
DEFAULT_SATISFACTION_SURVEY_REMINDER_EMAIL_TEMPLATE = "Supplier Satisfaction Survey Reminder"


class SupplierSatisfactionSurvey(Document):
	def before_insert(self):
		# Always the actual creation date, never user-set — the field is
		# read-only on the form for exactly this reason.
		self.survey_date = frappe.utils.nowdate()

		# Ratings rows are entirely system-populated (the Table field has
		# cannot_add_rows/cannot_delete_rows, and each row's own Criteria is
		# read-only) — this is the one place they ever get created, fixed
		# for this survey's whole life regardless of a later template
		# change. Only runs when nothing was already appended (e.g. by a
		# script inserting pre-built rows directly).
		if self.supplier and not self.ratings:
			criteria = get_rating_criteria_for_supplier(self.supplier)
			if not criteria:
				frappe.throw(
					frappe._(
						"No Rating Template is set for {0} (or with usable criteria) — set one on the "
						"Supplier or as the default in Supplier Lifecycle Settings before creating a "
						"Satisfaction Survey."
					).format(self.supplier)
				)
			for row in criteria:
				self.append("ratings", {"criteria": row.name})

	def validate(self):
		if not self.is_new():
			self._forbid_rating_row_changes()

		self._set_status()

		if is_internal_user():
			return
		if not self.is_new():
			self._forbid_portal_field_changes()
		# Portal (Supplier-role) users can only ever file a survey against
		# their own linked supplier — belt-and-suspenders alongside the
		# permission_query_conditions hook, which only filters list views.
		if self.supplier not in get_supplier_portal_suppliers(frappe.session.user):
			frappe.throw(frappe._("You can only submit a survey for your own supplier account."))

	def before_submit(self):
		# Can be created (by the scheduler or an internal user) before any
		# rating is filled in — this is the actual gate that stops it being
		# submitted early, from either the portal or the Desk form.
		if not self.ratings or any(not row.score for row in self.ratings):
			frappe.throw(frappe._("Every Rating must be scored before this survey can be submitted."))

	def after_insert(self):
		# The scheduler (create_pending_satisfaction_surveys) reads this
		# directly instead of querying this doctype per supplier every day —
		# keep it in sync the moment a survey is actually created, whether
		# that's the scheduler itself or an internal user creating one by
		# hand.
		frappe.db.set_value("Supplier", self.supplier, "last_satisfaction_survey_date", self.survey_date)
		self._notify_created()

	def on_cancel(self):
		# validate() (where _set_status() normally runs) isn't called on
		# cancel — only before_cancel/on_cancel are — so this is set
		# directly here instead.
		self.db_set("status", "Cancelled")

	def _set_status(self):
		# Reflects where this survey actually is, for both the Desk list
		# and the portal list — computed, never set by hand (the field is
		# read-only). docstatus is already the *target* value at this
		# point during submit (Frappe sets it before running validate()).
		if self.docstatus == 1:
			self.status = "Completed"
		elif self.ratings and all(row.score for row in self.ratings):
			self.status = "Ratings Given"
		elif any(row.score for row in self.ratings):
			self.status = "In Progress"
		else:
			self.status = "Open"

	def _forbid_portal_field_changes(self):
		# A Supplier fills in scores, issues and remarks only — everything
		# else is set by staff or the scheduler.
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in PORTAL_LOCKED_FIELDS:
			# Compared as text — the portal sends dates/checks as strings.
			if frappe.utils.cstr(self.get(fieldname)) != frappe.utils.cstr(before.get(fieldname)):
				frappe.throw(
					frappe._("{0} can't be changed.").format(frappe.bold(self.meta.get_label(fieldname)))
				)
		criteria_before = {row.name: row.criteria for row in before.ratings}
		if any(criteria_before.get(row.name) != row.criteria for row in self.ratings):
			frappe.throw(frappe._("A rating's criteria can't be changed."))

	def _forbid_rating_row_changes(self):
		# The grid's add/delete-row buttons are hidden client-side (see
		# supplier_satisfaction_survey.js), but that's Desk-UI-only — this is
		# what actually stops a row being added or removed via the API
		# (e.g. frappe.client.save from the portal edit page). Editing an
		# existing row's own Score is unaffected — only the row *set*
		# (by name) is locked, not its fields.
		existing_names = set(
			frappe.get_all(
				"Supplier Satisfaction Rating",
				filters={"parent": self.name, "parenttype": self.doctype, "parentfield": "ratings"},
				pluck="name",
			)
		)
		current_names = {row.name for row in self.ratings if row.name}
		if len(current_names) != len(self.ratings) or current_names != existing_names:
			frappe.throw(frappe._("Rows can't be added to or removed from the Ratings table."))

	def _notify_created(self):
		# Best-effort, like every other Supplier Lifecycle notification — a
		# missing template/account is a notification problem, not a reason
		# to fail the survey's own creation.
		try:
			self._notify_created_unsafe()
		except Exception:
			reraise_if_db_lock_error()
			frappe.log_error(
				title="Supplier Satisfaction Survey: failed to send creation email", message=frappe.get_traceback()
			)

	def _notify_created_unsafe(self):
		contact = get_survey_supplier_contact(self.supplier)
		if not contact.get("official_email"):
			return
		send_supplier_lifecycle_email(
			doctype=self.doctype,
			name=self.name,
			template_name=DEFAULT_SATISFACTION_SURVEY_CREATED_EMAIL_TEMPLATE,
			context=_survey_email_context(self, contact),
			recipients=[contact["official_email"]],
		)


PORTAL_LOCKED_FIELDS = ("supplier", "period", "survey_date", "is_system_generated", "last_reminder_sent", "amended_from")


def _survey_email_context(survey, contact):
	return {
		"firm_name": contact.get("firm_name"),
		"contact_person_name": contact.get("contact_person_name"),
		"company_name": resolve_supplier_lifecycle_company_name(),
		"survey_name": survey.name,
		"period": survey.period,
		"survey_date": frappe.utils.formatdate(survey.survey_date),
		"survey_link": get_survey_portal_link(survey.name),
	}


def get_survey_portal_link(name):
	# The Desk form link (get_url_to_form) is useless here — the supplier is
	# a portal-only user with no Desk access at all. This is the same
	# route the portal's own list page links each row to.
	return f"{frappe.utils.get_url()}/supplier-satisfaction-surveys/{name}"


def get_survey_supplier_contact(supplier):
	"""Supplier's own official email/contact/firm name for a Satisfaction
	Survey — prefers the linked Supplier KYC (submitted, most recent) for the
	richer contact_person_name, but falls back to the Supplier's own
	email_id/supplier_name since Satisfaction Surveys now apply to any
	enabled, non-frozen Supplier (see tasks.py), not only ones that went
	through this app's own KYC pipeline."""
	kyc_name = frappe.db.get_value(
		"Supplier KYC", {"supplier": supplier, "docstatus": 1}, "name", order_by="creation desc"
	)
	if kyc_name:
		contact = get_kyc_supplier_contact(kyc_name)
		if contact.get("official_email"):
			return contact

	supplier_doc = (
		frappe.db.get_value("Supplier", supplier, ["supplier_name", "email_id"], as_dict=True) or {}
	)
	return {
		"official_email": supplier_doc.get("email_id"),
		"contact_person_name": None,
		"firm_name": supplier_doc.get("supplier_name"),
	}


def resolve_rating_template(supplier):
	"""A Supplier's own Rating Template (set by staff on the Supplier
	record) always wins over the site-wide default — that's what lets one
	industry's suppliers get a different set of criteria from everyone
	else's. Returns None if neither is set, meaning no criteria show at
	all rather than falling back to some other ad-hoc list."""
	if supplier:
		supplier_template = frappe.db.get_value("Supplier", supplier, "rating_template")
		if supplier_template:
			return supplier_template
	return frappe.db.get_single_value("Supplier Lifecycle Settings", "default_rating_template")


def get_rating_criteria_for_supplier(supplier):
	"""Ordered [{"name": ..., "criteria_name": ...}] list to render as
	Ratings rows for this supplier's Satisfaction Survey, resolved via
	resolve_rating_template() above. Empty if no template applies at
	either level, or the resolved template has no (enabled) rows — a
	disabled Rating Criteria is dropped even if some template still
	references it, same as everywhere else in the app that reads this
	master."""
	template_name = resolve_rating_template(supplier)
	if not template_name:
		return []

	template = frappe.get_cached_doc("Satisfaction Rating Template", template_name)
	ordered_criteria_names = [row.criteria for row in template.criteria]
	if not ordered_criteria_names:
		return []

	rows = frappe.get_all(
		"Rating Criteria",
		filters={"name": ["in", ordered_criteria_names], "disabled": 0},
		fields=["name", "criteria_name"],
	)
	position = {name: idx for idx, name in enumerate(ordered_criteria_names)}
	rows.sort(key=lambda row: position.get(row.name, len(position)))
	return rows
