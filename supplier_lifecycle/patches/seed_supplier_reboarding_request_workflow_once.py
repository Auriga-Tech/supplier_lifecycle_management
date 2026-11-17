# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe


def execute():
	# Same reasoning as seed_supplier_kyc_workflow_once.py - a separate,
	# one-time patch so a deliberate later change to this Workflow (through
	# the Workflow Builder, or a deletion) actually sticks rather than
	# being silently reverted on every migrate.
	from supplier_lifecycle.supplier_lifecycle.install import install_supplier_reboarding_request_workflow

	install_supplier_reboarding_request_workflow()
