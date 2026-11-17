# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt

import frappe


def execute():
	from supplier_lifecycle.supplier_lifecycle.install import (
		backfill_default_attachment_save_failed_email_template,
	)

	backfill_default_attachment_save_failed_email_template()
