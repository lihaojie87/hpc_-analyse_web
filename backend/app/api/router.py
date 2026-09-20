from fastapi import APIRouter
from app.api.auth_routes import router as auth
from app.api.user_routes import router as users
from app.api.role_routes import router as roles
from app.api.health_routes import router as health
from app.api.template_routes import router as templates
from app.api.catalog_routes import router as catalog, public_router as public_catalog
from app.api.version_routes import router as versions
from app.api.audit_routes import router as audits
from app.api.import_routes import router as imports
from app.api.source_routes import router as sources
from app.api.sync_routes import router as sync
from app.api.event_routes import router as events
router=APIRouter()
router.include_router(auth,prefix="/api/v1")
router.include_router(users,prefix="/api/v1")
router.include_router(roles,prefix="/api/v1")
router.include_router(health)
router.include_router(templates,prefix='/api/v1')
router.include_router(catalog,prefix='/api/v1')
router.include_router(public_catalog,prefix='/api/v1')
router.include_router(versions,prefix='/api/v1')
router.include_router(audits,prefix='/api/v1')
router.include_router(imports,prefix='/api/v1')
router.include_router(sources,prefix='/api/v1')
router.include_router(sync,prefix='/api/v1')
router.include_router(events,prefix='/api/v1')
