# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe


def execute():
	# Same reasoning as seed_master_data_once.py / seed_email_templates_
	# once.py - a separate patch, not added to either of those, since
	# they've already run (and been recorded as done) on sites that had
	# already migrated past them; a new patch is what actually gets
	# picked up there.
	#
	# install_supplier_kyc_workflow() used to run on every migrate and
	# unconditionally re-synced the Workflow's states/transitions back to
	# their hardcoded spec whenever they drifted from it - not just
	# recreating a deleted Workflow, but silently reverting a genuine
	# customization made through the Workflow Builder (confirmed directly:
	# changed who's allowed to approve a KYC, ran migrate, the change was
	# wiped). Now only ever runs once, ever, so a deliberate change to the
	# Workflow — through the Builder, or a deletion — actually sticks.
	from supplier_lifecycle.supplier_lifecycle.install import install_supplier_kyc_workflow

	install_supplier_kyc_workflow()
