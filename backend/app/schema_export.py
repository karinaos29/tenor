"""Print the JSON Schema of every event, for TypeScript generation.

The frontend runs this through `npm run gen:types`; don't call it by hand
unless you're debugging the schema.
"""

import json

from pydantic.json_schema import GenerateJsonSchema

from pydantic import TypeAdapter

from pipeline.events import REST_MODELS, tenor_event_adapter


class _NoFieldTitles(GenerateJsonSchema):
    """Drop per-field titles; json2ts would turn each into a type alias (Ts1, Type2, ...)."""

    def field_title_should_be_set(self, schema) -> bool:
        return False


def event_schema() -> dict:
    """One root object referencing every wire type, so json2ts emits all of them."""
    union = tenor_event_adapter.json_schema(mode="serialization", schema_generator=_NoFieldTitles)
    defs = union.pop("$defs")
    defs["TenorEvent"] = {**union, "title": "TenorEvent"}
    properties = {"event": {"$ref": "#/$defs/TenorEvent"}}
    for model in REST_MODELS:
        extra = TypeAdapter(model).json_schema(mode="serialization", schema_generator=_NoFieldTitles)
        defs.update(extra.pop("$defs", {}))
        defs[model.__name__] = extra
        properties[model.__name__[0].lower() + model.__name__[1:]] = {"$ref": f"#/$defs/{model.__name__}"}
    return {
        "title": "TenorWire",
        "description": "Every type that crosses the wire. Generated root; import the member types.",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "$defs": defs,
    }


if __name__ == "__main__":
    print(json.dumps(event_schema(), indent=2))
