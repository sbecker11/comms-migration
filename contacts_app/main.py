"""Web UI for browsing and editing contacts/Contacts.yaml."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from contacts.store import (
    DEFAULT_CONTACTS_PATH,
    STANDARD_GROUPS,
    apply_contact_form,
    filter_contacts,
    find_contact,
    linkedin_display_value,
    load,
    new_contact_record,
    normalize_contact,
    paginate,
    save,
)

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Contacts Editor", version="0.1.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def _display_name(contact: dict[str, Any]) -> str:
    parts = [contact.get("first_name") or "", contact.get("last_name") or ""]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    if contact.get("organization"):
        return contact["organization"]
    emails = contact.get("emails") or []
    if emails:
        return emails[0].get("value") or contact.get("id", "Unknown")
    return contact.get("id", "Unknown")


templates.env.filters["display_name"] = _display_name


def _list_url(**params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return "/?" + urlencode(clean) if clean else "/"


@app.get("/", response_class=HTMLResponse)
def list_contacts(
    request: Request,
    q: str = Query(""),
    group: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    include_deleted: bool = Query(False),
) -> HTMLResponse:
    data = load()
    filtered = filter_contacts(
        data["contacts"],
        q=q,
        group=group,
        include_deleted=include_deleted,
    )
    page_items, total = paginate(filtered, page, per_page)
    total_pages = max(1, math.ceil(total / per_page))

    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "contacts": page_items,
            "meta": data["meta"],
            "q": q,
            "group": group,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "include_deleted": include_deleted,
            "list_url": _list_url,
        },
    )


def _detail_context(
    contact: dict[str, Any],
    meta: dict[str, Any],
    *,
    is_new: bool = False,
    return_query: str = "",
) -> dict[str, Any]:
    return {
        "contact": contact,
        "meta": meta,
        "groups": STANDARD_GROUPS,
        "linkedin_value": linkedin_display_value(contact.get("linkedin") or ""),
        "return_query": return_query,
        "is_new": is_new,
    }


@app.get("/contacts/new", response_class=HTMLResponse)
def new_contact_form(request: Request) -> HTMLResponse:
    data = load()
    contact = normalize_contact(new_contact_record())
    return templates.TemplateResponse(
        request,
        "detail.html",
        _detail_context(contact, data["meta"], is_new=True),
    )


@app.get("/contacts/{contact_id}", response_class=HTMLResponse)
def contact_detail(
    request: Request,
    contact_id: str,
    q: str = Query(""),
    group: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(25),
    include_deleted: bool = Query(False),
) -> HTMLResponse:
    data = load()
    contact = find_contact(data, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact = normalize_contact(contact)
    return templates.TemplateResponse(
        request,
        "detail.html",
        _detail_context(
            contact,
            data["meta"],
            return_query=urlencode(
                {
                    k: v
                    for k, v in {
                        "q": q,
                        "group": group,
                        "page": page,
                        "per_page": per_page,
                        "include_deleted": str(include_deleted).lower()
                        if include_deleted
                        else "",
                    }.items()
                    if v not in ("", "1", "25", "false")
                }
            ),
        ),
    )


def _parse_labeled_rows(labels: list[str], values: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for label, value in zip(labels, values, strict=False):
        value = (value or "").strip()
        if not value and not (label or "").strip():
            continue
        rows.append({"label": (label or "").strip(), "value": value})
    return rows


def _save_contact_from_form(
    data: dict[str, Any],
    contact: dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    organization: str,
    linkedin: str,
    notes: str,
    email_label: list[str],
    email_value: list[str],
    phone_label: list[str],
    phone_value: list[str],
    url_label: list[str],
    url_value: list[str],
    groups: list[str],
) -> str:
    apply_contact_form(
        contact,
        first_name=first_name,
        last_name=last_name,
        organization=organization,
        linkedin=linkedin,
        notes=notes,
        emails=_parse_labeled_rows(email_label, email_value),
        phones=_parse_labeled_rows(phone_label, phone_value),
        urls=[
            u
            for u in _parse_labeled_rows(url_label, url_value)
            if "linkedin.com" not in u.get("value", "").lower()
        ],
        groups=groups,
    )
    return contact["id"]


@app.post("/contacts/new")
def create_contact(
    first_name: str = Form(""),
    last_name: str = Form(""),
    organization: str = Form(""),
    linkedin: str = Form(""),
    notes: str = Form(""),
    email_label: list[str] = Form(default=[]),
    email_value: list[str] = Form(default=[]),
    phone_label: list[str] = Form(default=[]),
    phone_value: list[str] = Form(default=[]),
    url_label: list[str] = Form(default=[]),
    url_value: list[str] = Form(default=[]),
    groups: list[str] = Form(default=[]),
    return_query: str = Form(""),
) -> RedirectResponse:
    data = load()
    contact = new_contact_record()
    contact_id = _save_contact_from_form(
        data,
        contact,
        first_name=first_name,
        last_name=last_name,
        organization=organization,
        linkedin=linkedin,
        notes=notes,
        email_label=email_label,
        email_value=email_value,
        phone_label=phone_label,
        phone_value=phone_value,
        url_label=url_label,
        url_value=url_value,
        groups=groups,
    )
    data["contacts"].append(contact)
    save(data)
    suffix = f"?{return_query}" if return_query else ""
    return RedirectResponse(url=f"/contacts/{contact_id}{suffix}", status_code=303)


@app.post("/contacts/{contact_id}")
def save_contact(
    contact_id: str,
    first_name: str = Form(""),
    last_name: str = Form(""),
    organization: str = Form(""),
    linkedin: str = Form(""),
    notes: str = Form(""),
    email_label: list[str] = Form(default=[]),
    email_value: list[str] = Form(default=[]),
    phone_label: list[str] = Form(default=[]),
    phone_value: list[str] = Form(default=[]),
    url_label: list[str] = Form(default=[]),
    url_value: list[str] = Form(default=[]),
    groups: list[str] = Form(default=[]),
    return_query: str = Form(""),
) -> RedirectResponse:
    data = load()
    contact = find_contact(data, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact_id = _save_contact_from_form(
        data,
        contact,
        first_name=first_name,
        last_name=last_name,
        organization=organization,
        linkedin=linkedin,
        notes=notes,
        email_label=email_label,
        email_value=email_value,
        phone_label=phone_label,
        phone_value=phone_value,
        url_label=url_label,
        url_value=url_value,
        groups=groups,
    )
    save(data)
    suffix = f"?{return_query}" if return_query else ""
    return RedirectResponse(url=f"/contacts/{contact_id}{suffix}", status_code=303)
