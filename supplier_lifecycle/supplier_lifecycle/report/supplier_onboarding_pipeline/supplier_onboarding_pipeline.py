# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe
from frappe import _

NOT_STARTED_FIELDS = (
	"kyc_status",
	"background_check_status",
	"compliance_audit_status",
	"sampling_evaluation_status",
	"sign_off_status",
)


def execute(filters: dict | None = None):
	filters = filters or {}
	view_by = filters.get("view_by")

	if not view_by:
		frappe.throw(_("Select a View By option (Onboarding Request or Supplier KYC) to see this report."))

	if view_by == "Onboarding Request":
		return get_request_columns(), get_request_data(filters)

	return get_kyc_columns(), get_kyc_data(filters)


def get_kyc_columns() -> list[dict]:
	return [
		{"label": _("KYC"), "fieldname": "kyc", "fieldtype": "Link", "options": "Supplier KYC", "width": 130},
		{"label": _("Supplier Name"), "fieldname": "firm_name", "fieldtype": "Data", "width": 180},
		{"label": _("KYC Status"), "fieldname": "kyc_status", "fieldtype": "Data", "width": 100},
		{"label": _("Background Check"), "fieldname": "background_check_status", "fieldtype": "Data", "width": 130},
		{"label": _("Compliance Audit"), "fieldname": "compliance_audit_status", "fieldtype": "Data", "width": 130},
		{"label": _("Sampling Evaluation"), "fieldname": "sampling_evaluation_status", "fieldtype": "Data", "width": 140},
		{"label": _("Sign Off"), "fieldname": "sign_off_status", "fieldtype": "Data", "width": 100},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
	]


def get_kyc_data(filters: dict | None = None) -> list[dict]:
	filters = filters or {}
	company_name = filters.get("company_name") or ""
	# Every filter is bound as a query parameter and matched inside a fixed
	# query — an unset filter is passed as an empty string, which its own
	# `= ''` branch turns into "match everything". The SQL text never
	# changes with the filter values, so nothing from the filters can ever
	# reach the query as SQL.
	params = {
		"company_name": company_name,
		"company_name_like": f"%{company_name}%",
		"kyc": filters.get("kyc") or "",
	}

	# Each stage's own latest (by creation) record for the KYC — a supplier
	# who redid a stage shouldn't show stale data from an earlier attempt.
	# Onboarding documents only: re-boarding and renewal ones carry the same
	# KYC, and a cancelled one no longer counts.
	rows = frappe.db.sql(
		"""
		select
			vk.name as kyc,
			vk.firm_name,
			vk.status as kyc_status,
			vk.supplier as supplier,
			(
				select bc.overall_status
				from `tabSupplier Background Check` bc
				where bc.kyc = vk.name and bc.is_reboarding = 0 and bc.docstatus < 2
				order by bc.creation desc limit 1
			) as background_check_status,
			(
				select ca.outcome
				from `tabSupplier Compliance Audit` ca
				where ca.kyc = vk.name and ca.is_reboarding = 0 and ca.docstatus < 2 and ca.is_renewal = 0
				order by ca.creation desc limit 1
			) as compliance_audit_status,
			(
				select se.evaluation_outcome
				from `tabSupplier Sampling Evaluation` se
				where se.kyc = vk.name and se.is_reboarding = 0 and se.docstatus < 2 and se.is_renewal = 0
				order by se.creation desc limit 1
			) as sampling_evaluation_status,
			(
				select case when so.docstatus = 1 then
					(case when so.sign_off_failed then 'Failed' else 'Signed' end)
				else 'Draft' end
				from `tabSupplier Sign Off` so
				where so.kyc = vk.name and so.is_reboarding = 0 and so.docstatus < 2 and so.is_renewal = 0
				order by so.creation desc limit 1
			) as sign_off_status
		from `tabSupplier KYC` vk
		where (%(company_name)s = '' or vk.firm_name like %(company_name_like)s)
			and (%(kyc)s = '' or vk.name = %(kyc)s)
		order by vk.creation desc
		""",
		params,
		as_dict=True,
	)

	_fill_not_started(rows)
	return rows


def get_request_columns() -> list[dict]:
	return [
		{"label": _("Onboarding Request"), "fieldname": "request", "fieldtype": "Link", "options": "Supplier Onboarding Request", "width": 150},
		{"label": _("Company / Firm Name"), "fieldname": "company_name", "fieldtype": "Data", "width": 180},
		{"label": _("Request Status"), "fieldname": "request_status", "fieldtype": "Data", "width": 100},
		{"label": _("KYC"), "fieldname": "kyc", "fieldtype": "Link", "options": "Supplier KYC", "width": 130},
		{"label": _("KYC Status"), "fieldname": "kyc_status", "fieldtype": "Data", "width": 100},
		{"label": _("Background Check"), "fieldname": "background_check_status", "fieldtype": "Data", "width": 130},
		{"label": _("Compliance Audit"), "fieldname": "compliance_audit_status", "fieldtype": "Data", "width": 130},
		{"label": _("Sampling Evaluation"), "fieldname": "sampling_evaluation_status", "fieldtype": "Data", "width": 140},
		{"label": _("Sign Off"), "fieldname": "sign_off_status", "fieldtype": "Data", "width": 100},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
	]


def get_request_data(filters: dict | None = None) -> list[dict]:
	filters = filters or {}
	company_name = filters.get("company_name") or ""
	# Every filter is bound as a query parameter and matched inside a fixed
	# query — an unset filter is passed as an empty string, which its own
	# `= ''` branch turns into "match everything". The SQL text never
	# changes with the filter values, so nothing from the filters can ever
	# reach the query as SQL.
	params = {
		"company_name": company_name,
		"company_name_like": f"%{company_name}%",
		"kyc": filters.get("kyc") or "",
	}

	# Anchored on the Onboarding Request instead of the KYC, so a request
	# that hasn't had KYC started yet still shows up (the KYC-anchored view
	# above only ever sees suppliers who've reached KYC). Each request's
	# latest KYC (if any) is resolved once by the left join below and reused
	# as `vk` for every downstream stage lookup; a request with no KYC yet
	# keeps a null `vk`, so each stage falls through to "Not Started".
	rows = frappe.db.sql(
		"""
		select
			vor.name as request,
			vor.company_name,
			case vor.docstatus when 0 then 'Draft' when 1 then 'Submitted' else 'Cancelled' end as request_status,
			vk.name as kyc,
			vk.status as kyc_status,
			vk.supplier as supplier,
			(
				select bc.overall_status
				from `tabSupplier Background Check` bc
				where bc.kyc = vk.name and bc.is_reboarding = 0 and bc.docstatus < 2
				order by bc.creation desc limit 1
			) as background_check_status,
			(
				select ca.outcome
				from `tabSupplier Compliance Audit` ca
				where ca.kyc = vk.name and ca.is_reboarding = 0 and ca.docstatus < 2 and ca.is_renewal = 0
				order by ca.creation desc limit 1
			) as compliance_audit_status,
			(
				select se.evaluation_outcome
				from `tabSupplier Sampling Evaluation` se
				where se.kyc = vk.name and se.is_reboarding = 0 and se.docstatus < 2 and se.is_renewal = 0
				order by se.creation desc limit 1
			) as sampling_evaluation_status,
			(
				select case when so.docstatus = 1 then
					(case when so.sign_off_failed then 'Failed' else 'Signed' end)
				else 'Draft' end
				from `tabSupplier Sign Off` so
				where so.kyc = vk.name and so.is_reboarding = 0 and so.docstatus < 2 and so.is_renewal = 0
				order by so.creation desc limit 1
			) as sign_off_status
		from `tabSupplier Onboarding Request` vor
		left join `tabSupplier KYC` vk on vk.name = (
			select latest.name
			from `tabSupplier KYC` latest
			where latest.onboarding_request = vor.name
			order by latest.creation desc limit 1
		)
		where (%(company_name)s = '' or vor.company_name like %(company_name_like)s)
			and (%(kyc)s = '' or vk.name = %(kyc)s)
		order by vor.creation desc
		""",
		params,
		as_dict=True,
	)

	_fill_not_started(rows)
	return rows


def _fill_not_started(rows):
	for row in rows:
		for field in NOT_STARTED_FIELDS:
			row[field] = row.get(field) or _("Not Started")
