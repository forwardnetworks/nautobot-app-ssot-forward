from forward_nautobot.forms import FORWARD_PROFILE_FORM_FIELDS
from forward_nautobot.forms import ForwardConnectionProfileForm


def test_profile_form_exposes_expected_fields():
    form = ForwardConnectionProfileForm()

    if hasattr(form, "fields"):
        assert tuple(form.fields) == FORWARD_PROFILE_FORM_FIELDS
    else:
        assert form.field_names == FORWARD_PROFILE_FORM_FIELDS
