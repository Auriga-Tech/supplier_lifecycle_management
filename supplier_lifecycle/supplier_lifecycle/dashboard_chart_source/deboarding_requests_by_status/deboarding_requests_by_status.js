frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Deboarding Requests by Status"] = {
	method: "supplier_lifecycle.supplier_lifecycle.dashboard_chart_source.deboarding_requests_by_status.deboarding_requests_by_status.get",
	filters: [],
};
