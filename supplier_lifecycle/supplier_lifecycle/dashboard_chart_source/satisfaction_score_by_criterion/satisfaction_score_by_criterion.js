frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Satisfaction Score by Criterion"] = {
	method: "supplier_lifecycle.supplier_lifecycle.dashboard_chart_source.satisfaction_score_by_criterion.satisfaction_score_by_criterion.get",
	filters: [],
};
