frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Compliance Audit Outcomes"] = {
	method: "supplier_lifecycle.supplier_lifecycle.dashboard_chart_source.compliance_audit_outcomes.compliance_audit_outcomes.get",
	filters: [],
};
