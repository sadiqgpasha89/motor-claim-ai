from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from apps.api.routes import claims, ev, governance, intelligence, observability, sla, tp
from apps.api.schemas import LoginRequest
from packages.config import get_settings
from packages.contracts.errors import DomainError, ErrorCode, register_exception_handlers
from packages.observability.logging import correlation_id_var
from packages.security.auth import Role, UserContext, create_access_token, get_current_user
from services.claims.db import SessionLocal, get_db, init_db
from services.claims.models import User


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from scripts.seed_demo import ensure_seeded

    db = SessionLocal()
    try:
        ensure_seeded(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Enterprise Motor Claim AI Intelligence Solution (India-first, DEMO / SYNTHETIC)",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_correlation_id(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)

    register_exception_handlers(app)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "motor-claim-ai-api", "mode": "DEMO_SYNTHETIC"}

    @app.post("/api/v1/auth/login")
    def login(body: LoginRequest, db: Session = Depends(get_db)):
        u = db.query(User).filter(User.email == body.email).first()
        if not u:
            raise DomainError(ErrorCode.NOT_FOUND, f"Demo user '{body.email}' not found", status_code=404)
        ctx = UserContext(
            user_id=u.id,
            tenant_id=u.tenant_id,
            email=u.email,
            name=u.name,
            role=Role(u.role),
            partner_id=u.partner_id,
            branch=u.branch,
        )
        return {"access_token": create_access_token(ctx), "token_type": "bearer", "user": ctx.model_dump()}

    @app.get("/api/v1/auth/me")
    def me(user: UserContext = Depends(get_current_user)):
        return user.model_dump()

    @app.post("/api/v1/operations/seed-reset")
    def reset_seed(user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
        if user.role not in {Role.ADMIN, Role.CLAIMS_MANAGER}:
            raise DomainError(ErrorCode.NOT_AUTHORISED, "Admin or Claims Manager required to reset demo data", status_code=403)
        from scripts.seed_demo import reset_and_seed

        reset_and_seed(db)
        return {"status": "reseeded", "note": "All DEMO / SYNTHETIC claims reset cleanly."}

    app.include_router(claims.router)
    app.include_router(governance.router)
    app.include_router(tp.router)
    app.include_router(ev.router)
    app.include_router(sla.router)
    app.include_router(observability.router)
    app.include_router(intelligence.router)
    return app


app = create_app()
