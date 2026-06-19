def _ensure_django():
    try:
        from django import apps as _django_apps
        from django import setup as _django_setup
        from django.conf import settings
    except ModuleNotFoundError:
        return

    if not settings.configured:
        settings.configure(
            SECRET_KEY="nautobot-plugin-ssot-forward-tests",
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            INSTALLED_APPS=[],
            USE_I18N=True,
            USE_L10N=True,
            USE_TZ=True,
            LANGUAGE_CODE="en-us",
            TIME_ZONE="UTC",
        )

    if not _django_apps.apps.ready:
        _django_setup()


def test_profile_form_exposes_expected_fields():
    from forward_nautobot.forms import FORWARD_PROFILE_FORM_FIELDS, ForwardConnectionProfileForm

    _ensure_django()
    form = ForwardConnectionProfileForm()

    if hasattr(form, "fields"):
        assert tuple(form.fields) == FORWARD_PROFILE_FORM_FIELDS
    else:
        assert form.field_names == FORWARD_PROFILE_FORM_FIELDS
