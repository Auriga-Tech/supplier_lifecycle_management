# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from supplier_lifecycle.supplier_lifecycle.stage_sequencing import (
	block_if_onboarding_request_stopped,
	block_if_reboarding_completed,
	block_if_reboarding_request_stopped,
	enforce_sequential_cancellation,
	enforce_sequential_creation,
	force_override_stage,
	require_active_supplier_for_renewal,
	require_no_active_document_for_kyc,
)
from supplier_lifecycle.supplier_lifecycle.supplier_creation import (
	refresh_status_after_pass_cancelled,
	restore_status_after_draft_deleted,
	SUPPLIER_LIFECYCLE_STAGE_ONBOARDING_FAILED,
	SUPPLIER_LIFECYCLE_STAGE_REBOARDING_FAILED,
	SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_APPROVED,
	SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_IN_PROGRESS,
	SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_REJECTED,
	SUPPLIER_LIFECYCLE_STATUS_SAMPLING_APPROVED,
	SUPPLIER_LIFECYCLE_STATUS_SAMPLING_IN_PROGRESS,
	SUPPLIER_LIFECYCLE_STATUS_SAMPLING_REJECTED,
	get_disable_reason_for_supplier,
	get_kyc_supplier_contact,
	mark_supplier_status_in_progress,
	require_kyc_unless_reboarding,
	resolve_supplier_lifecycle_company_name,
	revert_stage_result,
	send_supplier_lifecycle_email,
	sync_onboarding_request_field,
	sync_supplier_field,
)
from supplier_lifecycle.supplier_lifecycle.db_errors import reraise_if_db_lock_error

DEFAULT_SUPPLIER_LIFECYCLE_PASSED_EMAIL_TEMPLATE = "Supplier Lifecycle Stage Passed"
DEFAULT_SUPPLIER_LIFECYCLE_FAILED_EMAIL_TEMPLATE = "Supplier Lifecycle Stage Failed"


class SupplierSamplingEvaluation(Document):
	def before_insert(self):
		self._derive_type_flags()
		require_active_supplier_for_renewal(self)
		self._resolve_reboarding_kyc_and_supplier()
		block_if_reboarding_completed(self)
		require_no_active_document_for_kyc(self)

	def _derive_type_flags(self):
		# sampling_type is the one field the user actually picks;
		# is_reboarding and is_renewal stay as plain, hidden, auto-computed
		# booleans so every existing is_reboarding-keyed check elsewhere in
		# the app keeps working completely unchanged — same reasoning as
		# Supplier Compliance Audit / Supplier Sign Off's own identical method.
		# is_renewal is true for the "Ad-hoc" Type here (see the field's
		# own description for why it isn't called is_adhoc).
		self.is_reboarding = 1 if self.sampling_type == "Reboarding" else 0
		self.is_renewal = 1 if self.sampling_type == "Ad-hoc" else 0

	def _resolve_reboarding_kyc_and_supplier(self):
		# Same pattern as Supplier Reboarding Request's own field resolution
		# — kyc/supplier stay mandatory and shown, just auto-filled from the
		# Reboarding Request instead of picked by hand, for a re-boarding
		# run.
		if not self.is_reboarding or not self.reboarding_request:
			return
		if not self.kyc:
			self.kyc = frappe.db.get_value("Supplier Reboarding Request", self.reboarding_request, "original_kyc")
		if not self.supplier:
			self.supplier = frappe.db.get_value("Supplier Reboarding Request", self.reboarding_request, "supplier")

	def validate(self):
		self._derive_type_flags()
		block_if_onboarding_request_stopped(self)
		block_if_reboarding_request_stopped(self)
		self._require_sample_identifier()
		self._warn_on_partial_or_failed_assessments()
		self._warn_on_unreceived_samples_with_final_outcome()
		sync_supplier_field(self)
		sync_onboarding_request_field(self)
		require_kyc_unless_reboarding(self)
		enforce_sequential_creation(self)
		# An Ad-hoc evaluation never touches the Supplier's status field at
		# all — see on_submit()'s own is_renewal branch, which is a pure
		# record of the result with zero side effects on the supplier.
		if self.is_renewal:
			return
		mark_supplier_status_in_progress(self, self._in_progress_status())

	def _in_progress_status(self):
		return (
			SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_IN_PROGRESS
			if self.is_reboarding
			else SUPPLIER_LIFECYCLE_STATUS_SAMPLING_IN_PROGRESS
		)

	def on_trash(self):
		block_if_onboarding_request_stopped(self)
		block_if_reboarding_request_stopped(self)
		restore_status_after_draft_deleted(self, self._in_progress_status())

	def _require_sample_identifier(self):
		for row in self.samples:
			if not row.item_code and not row.sample_description:
				frappe.throw(
					frappe._("Row #{0}: fill in either Item or What's Being Evaluated.").format(row.idx)
				)

	def _warn_on_partial_or_failed_assessments(self):
		# A warning, not a block — Evaluation Outcome is still the
		# reviewer's own separate judgment call; a row that doesn't fully
		# meet expectations is surfaced here so it isn't missed, rather
		# than auto-failing anything. Same pattern as Supplier Background
		# Check's own _warn_on_flagged_or_failed_compliance_checks.
		flagged = [
			frappe._("Row #{0} ({1}) — {2}").format(row.idx, row.criteria, row.assessment)
			for row in self.evaluation_results
			if row.assessment in ("Partially Meets", "Does Not Meet")
		]
		if flagged:
			frappe.msgprint(
				frappe._("The following Evaluation Results need attention: {0}").format(", ".join(flagged)),
				title=frappe._("Evaluation Results Need Review"),
				indicator="orange",
			)

	def _warn_on_unreceived_samples_with_final_outcome(self):
		# A warning, not a block — you can't have properly evaluated a
		# sample you haven't actually received yet, but the reviewer may
		# have a real reason to record a Rejected outcome anyway (e.g. the
		# supplier failed to ship it at all). Same pattern as
		# _warn_on_partial_or_failed_assessments above.
		if self.evaluation_outcome not in ("Approved", "Rejected"):
			return
		unreceived = [
			frappe._("Row #{0} — {1}").format(row.idx, row.sample_status)
			for row in self.samples
			if row.sample_status in ("Not Received", "In-Transit")
		]
		if unreceived:
			frappe.msgprint(
				frappe._(
					"Evaluation Outcome is {0}, but the following samples haven't been received yet: {1}"
				).format(self.evaluation_outcome, ", ".join(unreceived)),
				title=frappe._("Sample Not Yet Received"),
				indicator="orange",
			)

	def has_unreceived_samples(self):
		return any(row.sample_status in ("Not Received", "In-Transit") for row in self.samples)

	@frappe.whitelist()
	def load_evaluation_from_template(self):
		"""Populate evaluation_results from evaluation_template, replacing any existing rows."""
		if not self.evaluation_template:
			frappe.throw(frappe._("Set an Evaluation Template first."))

		template = frappe.get_doc("Sampling Evaluation Template", self.evaluation_template)
		self.evaluation_results = []
		for row in template.criteria:
			self.append("evaluation_results", {
				"criteria": row.criteria,
				"category": row.category,
			})

	def before_submit(self):
		require_active_supplier_for_renewal(self)
		self._require_evaluation_outcome_reviewed()
		self._require_samples_and_evaluation_rows()
		self._require_evaluation_template_still_enabled()
		self._require_evaluation_rows_assessed()
		self._require_sample_status_set()

	def _require_evaluation_outcome_reviewed(self):
		if self.evaluation_outcome == "Not Reviewed":
			frappe.throw(
				frappe._("Evaluation Outcome must be set to Approved or Rejected before submitting."),
				frappe.MandatoryError,
			)

	def _require_samples_and_evaluation_rows(self):
		if not self.samples:
			frappe.throw(frappe._("Add at least one row to Products / Samples before submitting."), frappe.MandatoryError)
		if not self.evaluation_results:
			frappe.throw(frappe._("Add at least one row to Evaluation Results before submitting."), frappe.MandatoryError)

	def _require_evaluation_template_still_enabled(self):
		# The Link field's own filter only keeps a disabled template out of
		# the picker going forward — it doesn't stop this document from
		# still pointing at one it picked before that template was
		# disabled, so this is checked again here (same pattern as Supplier
		# Compliance Audit's own template checks).
		if self.evaluation_template and frappe.db.get_value("Sampling Evaluation Template", self.evaluation_template, "disabled"):
			frappe.throw(
				frappe._("Evaluation Template {0} is disabled — pick a different one before submitting.").format(
					frappe.bold(self.evaluation_template)
				)
			)

	def _require_evaluation_rows_assessed(self):
		for row in self.evaluation_results:
			if not row.assessment:
				frappe.throw(
					frappe._("Row #{0}: set Assessment before submitting.").format(row.idx),
					frappe.MandatoryError,
				)

	def _require_sample_status_set(self):
		for row in self.samples:
			if not row.sample_status:
				frappe.throw(
					frappe._("Row #{0}: set Sample Status before submitting.").format(row.idx),
					frappe.MandatoryError,
				)

	@frappe.whitelist()
	def check_submit_readiness(self):
		# Same pattern as Supplier Background Check / Supplier Compliance
		# Audit's own check_submit_readiness — dry-runs before_submit()'s
		# preconditions so the client can surface a real blocking problem
		# before showing the Approved/Rejected confirmation.
		structural_error = None
		try:
			self._require_evaluation_outcome_reviewed()
			self._require_samples_and_evaluation_rows()
			self._require_evaluation_template_still_enabled()
			self._require_evaluation_rows_assessed()
			self._require_sample_status_set()
		except frappe.ValidationError as e:
			structural_error = str(e)
			frappe.clear_last_message()

		return {
			"structural_error": structural_error,
			"evaluation_outcome": self.evaluation_outcome,
			"has_unreceived_samples": self.has_unreceived_samples(),
		}

	def on_submit(self):
		if self.is_renewal:
			# An Ad-hoc evaluation (new product, spot check, etc.) is a
			# standalone record — it never disables the supplier and never
			# touches supplier_lifecycle_status/stage, Approved or Rejected.
			self._notify_outcome(
				DEFAULT_SUPPLIER_LIFECYCLE_FAILED_EMAIL_TEMPLATE
				if self.evaluation_outcome == "Rejected"
				else DEFAULT_SUPPLIER_LIFECYCLE_PASSED_EMAIL_TEMPLATE
			)
			return
		if self.evaluation_outcome == "Rejected":
			self._handle_rejected_result()
			self._notify_outcome(DEFAULT_SUPPLIER_LIFECYCLE_FAILED_EMAIL_TEMPLATE)
			return
		if self.supplier and self.evaluation_outcome == "Approved":
			status = (
				SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_APPROVED
				if self.is_reboarding
				else SUPPLIER_LIFECYCLE_STATUS_SAMPLING_APPROVED
			)
			frappe.db.set_value("Supplier", self.supplier, "supplier_lifecycle_status", status)
		self._notify_outcome(DEFAULT_SUPPLIER_LIFECYCLE_PASSED_EMAIL_TEMPLATE)

	def _notify_outcome(self, template_name):
		try:
			# An Ad-hoc evaluation has no kyc of its own (see
			# _resolve_reboarding_kyc_and_supplier's onboarding/re-boarding-
			# only scope) — its own original KYC still holds the same
			# firm/contact details, purely as a read-only contact-info
			# source here, nothing else.
			kyc_for_contact = self.kyc or (
				frappe.db.get_value("Supplier KYC", {"supplier": self.supplier, "docstatus": 1}, "name")
				if self.is_renewal and self.supplier
				else None
			)
			contact = get_kyc_supplier_contact(kyc_for_contact) if kyc_for_contact else {}
			context = {
				"firm_name": contact.get("firm_name"),
				"contact_person_name": contact.get("contact_person_name"),
				"company_name": resolve_supplier_lifecycle_company_name(),
				"stage_name": "Sampling Evaluation",
			}
			# Neither re-boarding nor an Ad-hoc evaluation enforce a stage
			# order (see stage_sequencing.enforce_sequential_creation's
			# is_reboarding and is_renewal branches), so "your next stage
			# is X" doesn't hold for either.
			if (
				template_name == DEFAULT_SUPPLIER_LIFECYCLE_PASSED_EMAIL_TEMPLATE
				and not self.is_reboarding
				and not self.is_renewal
			):
				context["next_stage"] = "Sign Off"
			send_supplier_lifecycle_email(
				doctype=self.doctype,
				name=self.name,
				template_name=template_name,
				context=context,
				recipients=[contact["official_email"]] if contact.get("official_email") else [],
			)
		except Exception:
			reraise_if_db_lock_error()
			frappe.log_error(
				title="Supplier Sampling Evaluation: failed to send outcome email", message=frappe.get_traceback()
			)

	def _handle_rejected_result(self):
		if not self.supplier:
			return
		if self.is_reboarding:
			# Deliberately does NOT touch disabled/is_frozen — see Supplier
			# Background Check's own _handle_failed_result for the full
			# reasoning (same rule, same doctype shape).
			frappe.db.set_value("Supplier", self.supplier, {
				"supplier_lifecycle_status": SUPPLIER_LIFECYCLE_STATUS_RESAMPLING_REJECTED,
				"supplier_lifecycle_stage": SUPPLIER_LIFECYCLE_STAGE_REBOARDING_FAILED,
			})
			return
		frappe.db.set_value("Supplier", self.supplier, {
			"disabled": 1,
			"supplier_lifecycle_status": SUPPLIER_LIFECYCLE_STATUS_SAMPLING_REJECTED,
			"supplier_lifecycle_stage": SUPPLIER_LIFECYCLE_STAGE_ONBOARDING_FAILED,
		})

	@frappe.whitelist()
	def force_override(self, reason):
		"""Lets a System Manager / Supplier Lifecycle Manager push past a
		Rejected result so later stages become creatable again, without
		pretending the result was actually Approved. See
		stage_sequencing.force_override_stage for the shared permission
		check, mandatory-reason enforcement, and Supplier re-enable logic."""
		if self.evaluation_outcome != "Rejected":
			frappe.throw(frappe._("Only a Rejected result can be force-overridden."))
		force_override_stage(self, reason)

	def on_cancel(self):
		block_if_onboarding_request_stopped(self)
		block_if_reboarding_request_stopped(self)
		enforce_sequential_cancellation(self)
		# An Ad-hoc evaluation never touched the Supplier in the first
		# place (see on_submit's own is_renewal branch) — nothing to
		# revert.
		if self.is_renewal:
			return
		self._revert_disable_if_this_was_the_rejected_one()
		if self.evaluation_outcome == "Approved":
			refresh_status_after_pass_cancelled(self)

	def _revert_disable_if_this_was_the_rejected_one(self):
		# Checks the actual current disable reason across all four stage
		# doctypes (get_disable_reason_for_supplier, which also excludes
		# force_overridden records) instead of just other Sampling
		# Evaluations — see Supplier Background Check's own same-named
		# method for the full reasoning.
		if self.evaluation_outcome != "Rejected" or not self.supplier:
			return
		if self.is_reboarding:
			revert_stage_result(self.supplier, reboarding_request=self.reboarding_request)
			return
		reason = get_disable_reason_for_supplier(self.supplier)
		if not reason or reason == {"doctype": self.doctype, "name": self.name}:
			frappe.db.set_value("Supplier", self.supplier, "disabled", 0)
		revert_stage_result(self.supplier, kyc=self.kyc)
