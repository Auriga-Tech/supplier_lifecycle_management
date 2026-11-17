# Supplier Lifecycle

Generic **supplier onboarding, ongoing engagement, and deboarding** workflow for ERPNext.

Every supplier goes through the same enforced pipeline — Onboarding Request → KYC → Background Check → Compliance Audit → Sampling Evaluation → Sign-off — before their Supplier record can be used, and a mirrored Deboarding pipeline before it's disabled again. A deboarded supplier can be brought back through its own Supplier Reboarding Request, which re-runs whichever of those same stages Settings marks mandatory for re-boarding. Compliance Audit and Sign-off can also run as a standalone periodic Renewal once a supplier is already active — and Sampling Evaluation as a standalone Ad-hoc re-check — independent of onboarding or re-boarding, for tracking recurring compliance/contract expiry and product re-sampling. Each stage's mandatory-ness, pass/fail method, and threshold is configurable per business, not hardcoded.

## User Manual

[![Download User Manual (PDF)](https://img.shields.io/badge/User%20Manual-Download%20PDF-0076DB?style=for-the-badge)](https://github.com/Auriga-Tech/supplier_lifecycle_management/raw/main/docs/Supplier_Lifecycle_User_Manual.pdf)

Step-by-step guide to every screen, setting, dashboard and email — [download the User Manual (PDF)](https://github.com/Auriga-Tech/supplier_lifecycle_management/raw/main/docs/Supplier_Lifecycle_User_Manual.pdf).

## Why this matters

Standard ERPNext gives every supplier a bare Supplier record — a name, a group, some contact fields — with no structured way to prove a supplier was actually vetted before you started buying from them, or to enforce that vetting consistently across every supplier added to the system. Today the workarounds are either onboarding suppliers directly into the Supplier master with no gating at all (a Purchase Order can go out to a supplier whose PAN/GSTIN was never validated and who never passed a compliance audit or background check), or running the actual vetting process outside ERPNext entirely — email threads, spreadsheets, Google Forms — with someone manually copying the outcome into the Supplier master days later and no record left of who approved what. This app closes that gap by putting the entire pipeline inside ERPNext itself: onboarding stops depending on someone remembering to follow the checklist, PAN/GSTIN get format- and (where India Compliance is installed) government-validated automatically, a failed stage disables the Supplier instead of quietly sitting unresolved, and a deboarded supplier is hard-blocked from every purchase and payment transaction (Purchase Orders, RFQs, Purchase Invoices and Receipts, Payment and Journal Entries — via ERPNext's own disabled-supplier rule), with the Deboarding Checklist's "Temporarily Enable Supplier" as the controlled way to settle final dues.

Two things worth weighing before adopting this on a live site:

- **Existing Suppliers aren't backfilled.** A Supplier created before this app was installed has no Supplier KYC or stage history at all — any dashboard or report that assumes every Supplier has a lifecycle status will show blanks for suppliers onboarded before adoption.
- **The pipeline adds real process overhead.** A team used to typing a Supplier name and moving on now goes through Onboarding Request → KYC → (optionally) Background Check → Compliance Audit → Sampling → Sign-off before a supplier is fully Active. For low-risk suppliers this can be a genuine slow-down — tune which stages are mandatory in Supplier Lifecycle Settings rather than running the full pipeline for every supplier by default.

## What it does

Everything lives under one workspace, organised into Onboarding, Deboarding, Ongoing Engagement, and Masters & Settings:

![The Supplier Lifecycle workspace](docs/screenshots/workspace.png?v=20261015)

**Onboarding.** A Supplier Onboarding Request (public web form or staff-entered) becomes a Supplier KYC on approval, which auto-creates the real Supplier/Contact/Address/Bank Account on submit. Whether PAN (India) and Tax ID (other countries) are mandatory is set in Settings:

![Supplier KYC form](docs/screenshots/supplier_kyc.png?v=20261015)

From there, up to four independently-configurable stages run in sequence — each disables the Supplier automatically on a Failed/Rejected outcome, and reverts that disable if it was the one responsible when cancelled. While a failure stands, no later stage can be started until it is cancelled or force-overridden:

![Supplier Background Check](docs/screenshots/supplier_background_check.png?v=20261015)
![Supplier Compliance Audit](docs/screenshots/supplier_compliance_audit.png?v=20261015)

Sampling Evaluation can be made mandatory only for specific Business Types, so it's skipped entirely — straight from Compliance Audit to Sign-off — for business types not listed:

![Supplier Sampling Evaluation](docs/screenshots/supplier_sampling_evaluation.png?v=20261015)

Sign-off is the final gate — contract and code of conduct sent and collected by email, activating the Supplier on success. Unlike the other three stages, a genuine Failed Sign-off can be retried directly, without cancelling the failed record first — the retry links back to the attempt it's replacing, and the KYC's own "Create" menu labels it distinctly as a retry, not a fresh attempt. A passing retry re-activates and unfreezes the Supplier; the failed attempt stays on record:

![Supplier Sign Off form, with the Retry Sign-off button](docs/screenshots/supplier_sign_off.png?v=20261015)
![Supplier KYC Create dropdown offering Retry Sign-off](docs/screenshots/supplier_kyc_create_dropdown.png?v=20261015)

**Ongoing Engagement.** Once active, Satisfaction Surveys are auto-created per supplier on a configurable cadence — reachable by suppliers through a login-gated portal, with no Desk access needed, where a supplier can only fill in scores, issues and remarks. The Supplier Engagement dashboard shows completed surveys, response rate, average score and overdue surveys for the last 12 months, plus the average score per criterion:

![Supplier Satisfaction Survey](docs/screenshots/supplier_satisfaction_survey.png?v=20261015)
![Supplier Engagement dashboard](docs/screenshots/dashboard_engagement.png?v=20261015)

**Deboarding.** A Supplier Deboarding Request captures the reason and a ratings review, with live visibility into any open Purchase Orders or unpaid invoices before it's approved:

![Supplier Deboarding Request](docs/screenshots/supplier_deboarding_request.png?v=20261015)

Once approved, a configurable Supplier Deboarding Checklist walks the closure through to completion — a signed Clearance Certificate is emailed to whichever contact is on file (KYC, Supplier's Primary Contact, or an additional address, deduplicated automatically) and collected back the same way — before disabling the Supplier on submit. The Checklist also has a toggle to temporarily re-enable the Supplier for a number of days set in Settings ("Temporary Enable Days", default 7) — for example, to let a final return or payment go through — which auto-disables again on expiry (nightly, 2 AM) unless someone flips it back off first. The same button is on the Supplier form while the supplier is Deboarded or being re-boarded; both act on the same Checklist, which records every toggle as a comment. The button relabels between "Temporarily Enable Supplier" and "Disable Supplier" depending on its current state:

![Supplier Deboarding Checklist](docs/screenshots/supplier_deboarding_checklist.png?v=20261015)
![Supplier Deboarding Checklist, before temporarily enabling the Supplier](docs/screenshots/supplier_deboarding_checklist_toggle_off.png?v=20261015)
![Supplier Deboarding Checklist, after temporarily enabling the Supplier — the button flips to Disable Supplier](docs/screenshots/supplier_deboarding_checklist_toggle_on.png?v=20261015)
![The same toggle on the Supplier form while the supplier is Deboarded](docs/screenshots/supplier_temporary_enable.png?v=20261015)

**Reboarding.** A deboarded supplier doesn't have to be re-created from scratch. A Supplier Reboarding Request re-runs whichever of Background Check, Compliance Audit, Sampling Evaluation, and Sign-off Settings marks mandatory for re-boarding — its own Pipeline Progress view tracks each stage the same way Onboarding does — and re-activates the Supplier once every mandatory stage has passed:

![Supplier Reboarding Request, showing its Pipeline Progress tracker](docs/screenshots/supplier_reboarding_request.png?v=20261015)

**Renewal & Ad-hoc.** Independent of any Onboarding/Reboarding run, a Compliance Audit or Sign-off can be created directly as a standalone **Renewal** (for periodic re-verification once a supplier is already active — compliance audit and contract validity dates, and whether an expiry auto-disables the Supplier, are all configurable), and a Sampling Evaluation as a standalone **Ad-hoc** re-check (for example, when a supplier introduces a new product) with zero effect on the Supplier's status either way. Both are only for active suppliers (Onboarded, Reboarded, or still being deboarded) and not for one on hold. If Settings disables suppliers on expiry, the expiry job (or a failed Renewal) disables the Supplier with status "Compliance Audit Expired" / "Contract Expired"; a Renewal of the same type can still be run on it and re-activates it when passed. Scheduled reminder emails flag both an upcoming Renewal expiry and an unfinished draft Renewal, each independently toggleable in Settings.

![Supplier Compliance Audit created as a standalone Renewal](docs/screenshots/supplier_compliance_audit_renewal.png?v=20261015)
![Supplier Sign Off created as a standalone Renewal](docs/screenshots/supplier_sign_off_renewal.png?v=20261015)
![Supplier Sampling Evaluation created as a standalone Ad-hoc re-check](docs/screenshots/supplier_sampling_evaluation_adhoc.png?v=20261015)

**Configuration.** One Settings screen controls almost everything above — no code change required:

![Supplier Lifecycle Settings](docs/screenshots/supplier_lifecycle_settings.png?v=20261015)

## Doctypes

| Area | Doctype | Purpose |
|---|---|---|
| Onboarding | Supplier Onboarding Request | Intake form; the only sanctioned entry point into KYC. |
| Onboarding | Supplier KYC | Core verification record every later stage links back to. |
| Onboarding | Supplier Background Check | Reference + compliance checks, with automatic pass/fail Result. |
| Onboarding | Supplier Background Check Reference | One reference contact + rating, linked to a Background Check. |
| Onboarding | Supplier Compliance Audit | Facility checklist, licenses & permits, insurance, financial stability; also usable standalone as a periodic Renewal. |
| Onboarding | Supplier Sampling Evaluation | Hands-on sample evaluation; mandatory only for configured Business Types; also usable standalone as an Ad-hoc re-check. |
| Onboarding | Supplier Sign Off | Final activation gate; supports a linked retry after a Failed outcome; also usable standalone as a periodic Renewal. |
| Ongoing Engagement | Supplier Satisfaction Survey | Auto-created per active supplier on a configurable cadence. |
| Deboarding | Supplier Deboarding Request | Reason + ratings review; approve/reject gate. |
| Deboarding | Supplier Deboarding Checklist | Offboarding task list; disables the Supplier on submit; also drives the time-boxed temporary-enable toggle. |
| Deboarding | Supplier Deboarding Checklist Template | Configurable offboarding task set a Checklist is built from. |
| Reboarding | Supplier Reboarding Request | Re-runs whichever stages are mandatory for re-boarding a deboarded supplier; re-activates the Supplier on completion. |
| Configuration | Supplier Lifecycle Settings | Single control panel — the only doctype with one record per site. |
| Masters | Rating Criteria / Rating Criteria Template | Used by Background Check References. |
| Masters | Satisfaction Rating Template | Used by Satisfaction Surveys. |
| Masters | Deboarding Rating Criteria / Deboarding Rating Template | Used by Deboarding Requests. |
| Masters | Compliance Check Type / Source / Template | Used by Background Check's compliance checks table. |
| Masters | Audit Checklist Template | Used by Compliance Audit's checklist tab. |
| Masters | License Type / Issuing Authority / Licenses and Permits Template | Used by Compliance Audit's licenses tab. |
| Masters | Insurance Type / Coverage Type / Insurer / Insurance Template | Used by Compliance Audit's insurance tab. |
| Masters | Sampling Evaluation Template | Used by Sampling Evaluation's scoring criteria. |
| Masters | Sampling Mandatory Override | Business Types where Sampling Evaluation is mandatory during re-boarding. |
| Masters | State | India-specific address state list. |

## Supplier status on the Supplier

Every Supplier created through the app carries two read-only fields kept up to date automatically: **Supplier Lifecycle Stage** (the big picture — Onboarding in Process, Onboarding Failed, Onboarded, Deboarding in Process, Deboarding Failed, Deboarded, Reboarding in Process, Reboarding Failed, Reboarded) and **Supplier Lifecycle Status** (the detail — e.g. Background Verified, Sign Off Failed, Re-Sampling In Progress, Active, Compliance Audit Expired, Temporarily Enabled, Disabled). Every submit, cancel and draft deletion puts both back to what is actually true.

## Cancel / amend behavior

- **Cancel**: each of the four onboarding stage doctypes reverts the disable it itself caused, but only if it was the one responsible — if another still-submitted Failed/Rejected record for the same supplier exists, the Supplier correctly stays disabled. Cancelling a stage is blocked while a later stage exists for the same KYC — submitted or still a draft (cancel or delete later stages first, newest first). The same applies during re-boarding, scoped to that Supplier Reboarding Request.
- **Stage order**: a later stage can't be started while an earlier one has failed (cancel or force-override it first), and an earlier stage can't be added once a later one exists.
- **Deboarding / Reboarding**: cancelling a Deboarding Request (only possible before its Checklist exists) returns the supplier to Onboarded/Reboarded and undoes its own freeze; cancelling a Checklist returns the supplier to Deboarding in Process (Checklists cancel newest first); cancelling a Reboarding Request returns the supplier to the stage it had before approval.
- **Renewal / Ad-hoc**: not part of any pipeline sequence, so none of the above blocking applies — a Renewal Compliance Audit/Sign-off or an Ad-hoc Sampling Evaluation can be created and cancelled freely, at most one draft at a time per supplier. A Renewal's disable-on-expiry consequence (if the relevant Settings checkbox is on) is re-checked against the Supplier's actual current expiry date on cancel, not just reverted blindly.
- **Amend**: none of these doctypes support Frappe's native amendment — a cancelled stage document must be replaced with a fresh one. Supplier Sign Off is the one exception: after a genuine Failed outcome, a retry can be created *without* cancelling the failed record first, linked back to the attempt it's retrying.

## Reporting

Four built-in reports: **Supplier Onboarding Pipeline** (every supplier's status across all four stages in one table, viewable by Onboarding Request or by KYC), **Supplier Reboarding Pipeline**, **Supplier Deboarding Pipeline**, and **Suppliers Due for Re-Audit**. Four dashboards (cards + charts) cover Onboarding, Reboarding, Ongoing Engagement, and Deboarding. Anything beyond these — cross-supplier trend analysis over time, for example — needs a custom report, same as any Frappe app.

## Compatibility

Tested against **Frappe 16 / ERPNext 16**. Not verified against v14 or v15. The India-specific PAN/GSTIN validation and address-fetch features additionally need the [India Compliance](https://github.com/resilient-tech/india-compliance) app installed — everything else works without it.

## Known limitations / roadmap

- **No standalone shortcut to just re-enable a deboarded supplier.** The only ways back today are the full Supplier Reboarding Request (re-running mandatory stages) or the time-boxed "Temporarily Enable Supplier" toggle (on the Deboarding Checklist or the Supplier form) — there's no permanent "flip it back on" option.
- **No multi-company scoping decided yet** — whether supplier lifecycle status and enforcement should apply per Company, or stay global across companies on a multi-company site, is still open.
- **Onboarding-stage emails aren't threaded** into one conversation — each stage's email arrives separately in the supplier's inbox.

## Install

```bash
bench get-app https://github.com/Auriga-Tech/supplier_lifecycle_management.git
bench --site <your-site> install-app supplier_lifecycle
bench --site <your-site> migrate
bench restart
```

Requires a working Frappe bench with **Frappe v16** and **ERPNext v16** already installed on the target site. Installing the app sets everything up once on that site: roles, Supplier custom fields, the Supplier Lifecycle roles' access to Supplier / Address / Contact / Bank Account, workflows, email templates, default templates and Settings defaults — nothing further to configure before using it, and every default is adjustable afterward in **Supplier Lifecycle Settings**. Later `migrate` runs never overwrite what a site has changed; they only re-create anything essential that has gone missing.

## License

MIT
