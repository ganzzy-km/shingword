"""2.0 authenticated API adapter; legacy routes are not co-registered."""
from .auth_api import bp, install_auth


def register_v2(app):
    from .baze_provider import install_provider
    install_provider(app)
    app.register_blueprint(bp)
    install_auth(app)
    from .essays import bp as essays
    app.register_blueprint(essays)
    from .analysis_api import bp as analyses
    app.register_blueprint(analyses)
    from .annotations_api import bp as annotations
    app.register_blueprint(annotations)
    from .library_api import bp as library
    app.register_blueprint(library)
    from .ocr_api import bp as ocr
    app.register_blueprint(ocr)
    from .quote_api import bp as quotations
    app.register_blueprint(quotations)
    from .ai_api import bp as ai
    app.register_blueprint(ai)

    from .operations_api import bp as operations
    app.register_blueprint(operations)

    from .writing_tools_api import bp as writing_tools
    app.register_blueprint(writing_tools)
