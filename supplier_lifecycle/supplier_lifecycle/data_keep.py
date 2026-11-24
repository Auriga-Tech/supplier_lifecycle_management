# Copyright (c) 2026, Auriga IT and contributors
# For license information, please see license.txt
"""Keep the Supplier Lifecycle data across an uninstall and a new install.

``bench uninstall-app`` drops the table of every Supplier Lifecycle DocType. Before that happens
``before_uninstall`` copies the records into one plain table (``__supplier_lifecycle_kept``). It is not a
DocType, so the uninstall leaves it alone. ``after_install`` puts the records back and empties the copy once
every record came back.

Records come back with ``db_insert``: names, owners and dates stay as they were, and no hook runs (no
validation, no emails). A record that already exists is never changed.

The app's own fields on Supplier, Purchase Invoice, Contact, Address and Bank Account are not copied: the
uninstall deletes their Custom Field records but keeps the columns and values.

Setting ``supplier_lifecycle_drop_data_on_uninstall`` to 1 in the site config skips the copy.
"""

import json
from itertools import batched, chain

import frappe
from frappe.utils import cint, now
from pypika import Table

TABLE = "__supplier_lifecycle_kept"
MODULE = "Supplier Lifecycle"
PAGE = 500


def keep_data_enabled():
	"""False when site config ``supplier_lifecycle_drop_data_on_uninstall`` is 1: a clean uninstall."""
	return not cint(frappe.conf.get("supplier_lifecycle_drop_data_on_uninstall"))


class KeptData:
	"""Save the Supplier Lifecycle records to the copy table and restore them from it."""

	def __init__(self):
		self.table = Table(TABLE)
		self.names = set()  # record names seen while saving, to pick the naming counters

	# ------------------------------------------------------------------ save
	def save(self):
		"""Replace the copy with the current records and return the row count.

		A site with no records never replaces an older copy, so a second uninstall cannot erase the first."""
		rows = self.document_rows()
		first = next(rows, None)
		if first is None:
			return 0
		self.ensure_table()
		frappe.qb.from_(self.table).delete().run()
		count = self.write(chain([first], rows))
		count += self.write(self.series_rows())
		frappe.logger("supplier_lifecycle").info(f"Kept {count} Supplier Lifecycle rows in {TABLE}")
		return count

	@staticmethod
	def table_present():
		"""``frappe.db.table_exists`` only knows ``tab`` tables, so look at the real table list."""
		return TABLE in frappe.db.get_tables(cached=False)

	def ensure_table(self):
		"""Create the copy table. Not a DocType, so the ORM can't create it - plain DDL (commits)."""
		if self.table_present():
			return
		frappe.db.sql_ddl(
			f"""create table `{TABLE}` (
				`kind` varchar(20) not null,
				`doctype` varchar(140) not null,
				`name` varchar(255) not null,
				`data` longtext,
				`kept_on` datetime,
				primary key (`kind`, `doctype`, `name`)
			) engine=InnoDB row_format=dynamic character set=utf8mb4 collate=utf8mb4_unicode_ci"""
		)

	def write(self, rows):
		count = 0
		for batch in batched(rows, 200):
			query = frappe.qb.into(self.table).columns("kind", "doctype", "name", "data", "kept_on")
			for kind, doctype, name, data in batch:
				query = query.insert(kind, doctype, name, json.dumps(data, default=str), now())
			query.run()
			count += len(batch)
		return count

	def document_rows(self):
		"""One row per record of every DocType of the module; child rows travel inside their parent."""
		for doctype in frappe.get_all(
			"DocType", filters={"module": MODULE, "istable": 0}, pluck="name", order_by="name"
		):
			meta = frappe.get_meta(doctype)
			if meta.issingle:
				yield from self.single_row(meta)
			elif not meta.get("is_virtual") and frappe.db.table_exists(doctype):
				yield from self.records(meta)

	def single_row(self, meta):
		values = frappe.db.get_singles_dict(meta.name)  # only the stored values
		children = self.children_of(meta.name, self.table_fields(meta), [meta.name]).get(meta.name, {})
		if values or children:
			yield "single", meta.name, meta.name, {"values": values, "children": children}

	def records(self, meta):
		tables = self.table_fields(meta)
		start = 0
		while page := frappe.get_all(
			meta.name,
			fields=["*"],
			order_by="creation asc, name asc",
			offset=start,
			limit=PAGE,
		):
			children = self.children_of(meta.name, tables, [row.name for row in page])
			for row in page:
				self.names.add(row.name)
				yield "doc", meta.name, row.name, {"values": row, "children": children.get(row.name, {})}
			start += PAGE

	def series_rows(self):
		"""Naming counters of the kept records (SOR-2026-, KYC-2026- ...), so new names don't repeat."""
		series = Table("tabSeries")  # Series is a plain table, not a DocType
		for name, current in frappe.qb.from_(series).select(series.name, series.current).run():
			if name and any(record.startswith(name) for record in self.names):
				yield "series", "Series", name, {"current": current}

	@staticmethod
	def table_fields(meta):
		return {df.fieldname: df.options for df in meta.get_table_fields()}

	@staticmethod
	def children_of(doctype, tables, parents):
		"""{parent: {fieldname: [child rows]}} read straight from the child tables."""
		found = {}
		for fieldname, child in tables.items():
			if not parents or not frappe.db.table_exists(child):
				continue
			rows = frappe.get_all(
				child,
				filters={"parent": ["in", parents], "parenttype": doctype, "parentfield": fieldname},
				fields=["*"],
				order_by="idx asc",
			)
			for row in rows:
				found.setdefault(row.parent, {}).setdefault(fieldname, []).append(row)
		return found

	# ------------------------------------------------------------------ restore
	def has_data(self):
		return bool(self.table_present() and frappe.qb.from_(self.table).select("kind").limit(1).run())

	def restore(self):
		"""Recreate the missing kept records, put back the Settings values and lift the naming counters.

		Each record goes back in its own savepoint, so one bad record does not stop the rest. The copy is
		emptied only when nothing failed; otherwise it stays and every failure is in the Error Log.
		Return {"created": n, "existing": n, "skipped": n, "failed": n}."""
		summary = {"created": 0, "existing": 0, "skipped": 0, "failed": 0}
		if not self.has_data():
			return summary
		for kind, doctype, rows in self.read(("doc", "single")):
			if kind == "single":
				for _, data in rows:
					self.restore_single(doctype, data, summary)
			else:
				self.restore_records(doctype, rows, summary)
		self.restore_series()
		if not summary["failed"]:
			frappe.qb.from_(self.table).delete().run()  # personal data (KYC) must not stay longer than needed
		frappe.logger("supplier_lifecycle").info(f"Restored Supplier Lifecycle data from {TABLE}: {summary}")
		return summary

	def read(self, kinds):
		"""Yield (kind, doctype, [(name, data)]) pages of the kept rows."""
		start = 0
		while page := (
			frappe.qb.from_(self.table)
			.select("kind", "doctype", "name", "data")
			.where(self.table.kind.isin(kinds))
			.orderby(self.table.kind)
			.orderby(self.table.doctype)
			.orderby(self.table.name)
			.limit(PAGE)
			.offset(start)
			.run()
		):
			by_group = {}
			for kind, doctype, name, data in page:
				by_group.setdefault((kind, doctype), []).append((name, json.loads(data)))
			for (kind, doctype), rows in by_group.items():
				yield kind, doctype, rows
			start += PAGE

	def restore_records(self, doctype, rows, summary):
		if not frappe.db.table_exists(doctype):  # the DocType no longer exists in this version
			summary["skipped"] += len(rows)
			return
		existing = set(frappe.get_all(doctype, filters={"name": ["in", [n for n, _ in rows]]}, pluck="name"))
		for name, data in rows:
			if name in existing:
				summary["existing"] += 1
				continue
			def put_back(data=data):
				self.insert(doctype, data["values"], data["children"])

			if self.safely(doctype, name, put_back):
				summary["created"] += 1
			else:
				summary["failed"] += 1

	def restore_single(self, doctype, data, summary):
		"""Kept values replace what the install set: the restore runs before any default is written."""

		def put_back():
			for field, value in data["values"].items():
				frappe.db.set_single_value(doctype, field, value, update_modified=False)
			for fieldname, rows in data["children"].items():
				child = self.child_doctype(doctype, fieldname)
				if not child or not frappe.db.table_exists(child):
					continue
				frappe.db.delete(child, {"parent": doctype, "parenttype": doctype, "parentfield": fieldname})
				self.insert_children(doctype, {fieldname: rows})

		if not frappe.db.exists("DocType", doctype):
			summary["skipped"] += 1
		elif self.safely(doctype, doctype, put_back):
			summary["created"] += 1
		else:
			summary["failed"] += 1

	@staticmethod
	def safely(doctype, name, fn):
		frappe.db.savepoint("supplier_lifecycle_restore")
		try:
			fn()
			return True
		except Exception:
			frappe.db.rollback(save_point="supplier_lifecycle_restore")
			frappe.log_error(f"Supplier Lifecycle: could not restore {doctype} {name}")
			return False

	def insert(self, doctype, values, children):
		frappe.get_doc({**values, "doctype": doctype}).db_insert()
		self.insert_children(doctype, children)

	def insert_children(self, doctype, children):
		for fieldname, rows in children.items():
			child = self.child_doctype(doctype, fieldname)
			if not child or not frappe.db.table_exists(child):
				continue
			for row in rows:
				frappe.get_doc({**row, "doctype": child}).db_insert()

	@staticmethod
	def child_doctype(doctype, fieldname):
		df = frappe.get_meta(doctype).get_field(fieldname)
		return df.options if df else None

	def restore_series(self):
		series = Table("tabSeries")
		for _, _, rows in self.read(("series",)):
			for name, data in rows:
				current = frappe.qb.from_(series).select(series.current).where(series.name == name).run()
				if not current:
					frappe.qb.into(series).columns("name", "current").insert(name, data["current"]).run()
				elif cint(current[0][0]) < cint(data["current"]):
					frappe.qb.update(series).set(series.current, data["current"]).where(
						series.name == name
					).run()
