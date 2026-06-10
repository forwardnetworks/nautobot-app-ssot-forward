"""UI stubs for the Forward Nautobot plugin."""

try:
    from django.http import HttpResponse
    from django.views import View
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
    class HttpResponse:  # type: ignore[too-many-ancestors]
        def __init__(self, content="", status=200, content_type="text/html"):
            self.content = content
            self.status_code = status
            self.content_type = content_type

    class View:  # type: ignore[too-many-ancestors]
        @classmethod
        def as_view(cls, *args, **kwargs):
            def _view(*view_args, **view_kwargs):
                instance = cls()
                if hasattr(instance, "get"):
                    return instance.get(*view_args, **view_kwargs)
                return HttpResponse()

            return _view


class ForwardHomeView(View):
    def get(self, request=None, *args, **kwargs):
        return HttpResponse(
            "<h1>Forward Networks</h1>"
            "<p>Forward Nautobot plugin scaffold.</p>"
            "<p>Use the jobs page to preview or sync a Forward network.</p>"
        )


class ForwardConfigurationView(View):
    def get(self, request=None, *args, **kwargs):
        return HttpResponse(
            "<h1>Forward Configuration</h1>"
            "<p>Configure the Forward connection via job inputs for now.</p>"
        )

