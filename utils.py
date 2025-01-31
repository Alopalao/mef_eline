"""Utility functions."""
import functools
from pathlib import Path

from flask import request
from openapi_core import create_spec
from openapi_core.contrib.flask import FlaskOpenAPIRequest
from openapi_core.validation.request.validators import RequestValidator
from openapi_spec_validator import validate_spec
from openapi_spec_validator.readers import read_from_filename
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from kytos.core import log
from kytos.core.events import KytosEvent


def map_evc_event_content(evc, **kwargs):
    """Returns a set of values from evc to be used for content"""
    return kwargs | {"evc_id": evc.id,
                     "name": evc.name,
                     "metadata": evc.metadata,
                     "active": evc._active,
                     "enabled": evc._enabled,
                     "uni_a": evc.uni_a.as_dict(),
                     "uni_z": evc.uni_z.as_dict()}


def emit_event(controller, name, context="kytos/mef_eline", content=None):
    """Send an event when something happens with an EVC."""
    event_name = f"{context}.{name}"
    event = KytosEvent(name=event_name, content=content)
    controller.buffers.app.put(event)


def notify_link_available_tags(controller, link, src_func=None):
    """Notify link available tags."""
    emit_event(controller, "link_available_tags", content={
        "link": link,
        "src_func": src_func
    })


def compare_endpoint_trace(endpoint, vlan, trace):
    """Compare and endpoint with a trace step."""
    if vlan and "vlan" in trace:
        return (
            endpoint.switch.dpid == trace["dpid"]
            and endpoint.port_number == trace["port"]
            and vlan == trace["vlan"]
        )
    return (
        endpoint.switch.dpid == trace["dpid"]
        and endpoint.port_number == trace["port"]
    )


def compare_uni_out_trace(uni, trace):
    """Check if the trace last step (output) matches the UNI attributes."""
    # keep compatibility for old versions of sdntrace-cp
    if "out" not in trace:
        return True
    if not isinstance(trace["out"], dict):
        return False
    uni_vlan = uni.user_tag.value if uni.user_tag else None
    return (
        uni.interface.port_number == trace["out"].get("port")
        and uni_vlan == trace["out"].get("vlan")
    )


def load_spec():
    """Validate openapi spec."""
    napp_dir = Path(__file__).parent
    yml_file = napp_dir / "openapi.yml"
    spec_dict, _ = read_from_filename(yml_file)

    validate_spec(spec_dict)

    return create_spec(spec_dict)


def validate(spec):
    """Decorator to validate a REST endpoint input.

    Uses the schema defined in the openapi.yml file
    to validate.
    """

    def validate_decorator(func):
        @functools.wraps(func)
        def wrapper_validate(*args, **kwargs):
            try:
                data = request.get_json()
            except BadRequest:
                result = "The request body is not a well-formed JSON."
                log.debug("create_circuit result %s %s", result, 400)
                raise BadRequest(result) from BadRequest
            if data is None:
                result = "The request body mimetype is not application/json."
                log.debug("update result %s %s", result, 415)
                raise UnsupportedMediaType(result)

            validator = RequestValidator(spec)
            openapi_request = FlaskOpenAPIRequest(request)
            result = validator.validate(openapi_request)
            if result.errors:
                error_response = (
                    "The request body contains invalid API data."
                )
                errors = result.errors[0]
                if hasattr(errors, "schema_errors"):
                    schema_errors = errors.schema_errors[0]
                    error_log = {
                        "error_message": schema_errors.message,
                        "error_validator": schema_errors.validator,
                        "error_validator_value": schema_errors.validator_value,
                        "error_path": list(schema_errors.path),
                        "error_schema": schema_errors.schema,
                        "error_schema_path": list(schema_errors.schema_path),
                    }
                    log.debug("Invalid request (API schema): %s", error_log)
                    error_response += f" {schema_errors.message} for field"
                    error_response += (
                        f" {'/'.join(map(str,schema_errors.path))}."
                    )
                raise BadRequest(error_response) from BadRequest
            return func(*args, data=data, **kwargs)

        return wrapper_validate

    return validate_decorator
