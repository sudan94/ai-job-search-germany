"""CV upload and the parsed profile."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.cv.profile import extract_text, get_active_profile, save_profile
from app.db import get_db
from app.schemas import CVOut, CVTextIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cv", tags=["cv"])

MAX_BYTES = 5 * 1024 * 1024


@router.get("", response_model=CVOut | None)
def read_cv(db: Session = Depends(get_db)) -> CVOut | None:
    profile = get_active_profile(db)
    return CVOut.from_model(profile) if profile else None


@router.post("/upload", response_model=CVOut)
async def upload_cv(file: UploadFile = File(...), db: Session = Depends(get_db)) -> CVOut:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="CV file must be under 5 MB.")
    try:
        extracted = extract_text(file.filename or "cv.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        profile, warnings = save_profile(
            db,
            filename=file.filename or "cv",
            text=extracted.text,
            page_count=extracted.pages,
        )
    except Exception as exc:
        logger.exception("CV parsing failed")
        raise HTTPException(status_code=502, detail=f"Could not process the CV: {exc}") from exc
    return CVOut.from_model(profile, warnings)


@router.post("/text", response_model=CVOut)
def upload_cv_text(payload: CVTextIn, db: Session = Depends(get_db)) -> CVOut:
    try:
        profile, warnings = save_profile(db, filename=payload.filename, text=payload.text)
    except Exception as exc:
        logger.exception("CV parsing failed")
        raise HTTPException(status_code=502, detail=f"Could not process the CV: {exc}") from exc
    return CVOut.from_model(profile, warnings)


@router.get("/raw")
def read_cv_raw(db: Session = Depends(get_db)) -> dict:
    profile = get_active_profile(db)
    if profile is None:
        raise HTTPException(status_code=404, detail="No CV on file")
    return {"filename": profile.filename, "text": profile.raw_text}
