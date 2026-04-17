"""Google Product Feed — read-only snapshot of product data from Google Merchant Center."""

import json

import frappe
from frappe.model.document import Document


class GoogleProductFeed(Document):
    def before_save(self):
        self._render_issues_display()

    def _render_issues_display(self):
        """Render the issues JSON as human-readable HTML."""
        if not self.issues:
            self.issues_display = ""
            return

        try:
            issues = json.loads(self.issues)
        except (json.JSONDecodeError, TypeError):
            self.issues_display = ""
            return

        if not issues:
            self.issues_display = '<p style="color: var(--green-500);">No issues found.</p>'
            return

        html = '<div class="feed-issues">'
        for issue in issues:
            severity = issue.get("severity", "")
            color = "var(--red-500)" if "ERROR" in severity or "DISAPPROVED" in severity else "var(--orange-500)"
            html += f"""
                <div style="border-left: 3px solid {color}; padding: 8px 12px; margin-bottom: 8px; background: var(--bg-color); border-radius: 0 4px 4px 0;">
                    <div style="font-weight: 600;">{frappe.utils.escape_html(issue.get("description", issue.get("code", "Unknown issue")))}</div>
                    <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                        {frappe.utils.escape_html(issue.get("detail", ""))}
                    </div>
                    <div style="font-size: 11px; color: var(--text-light); margin-top: 4px;">
                        Attribute: {frappe.utils.escape_html(issue.get("attribute", "N/A"))}
                        &middot; Severity: {frappe.utils.escape_html(severity)}
                    </div>
                </div>
            """
        html += "</div>"
        self.issues_display = html
