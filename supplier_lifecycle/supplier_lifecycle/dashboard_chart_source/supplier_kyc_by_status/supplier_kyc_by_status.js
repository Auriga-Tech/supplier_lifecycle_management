frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Supplier KYC by Status"] = {
	method: "supplier_lifecycle.supplier_lifecycle.dashboard_chart_source.supplier_kyc_by_status.supplier_kyc_by_status.get",
	filters: [],
};
