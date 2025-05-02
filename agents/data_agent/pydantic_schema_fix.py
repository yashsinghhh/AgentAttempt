"""
Schema fixing utilities using Pydantic to make MCP tool schemas compatible with Gemini.
"""
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field, create_model


class ItemType(BaseModel):
    """Schema for array item types."""
    type: str = "string"


class SchemaProperty(BaseModel):
    """Schema for individual properties in a JSON schema."""
    type: str
    description: Optional[str] = None
    items: Optional[ItemType] = None
    default: Optional[Any] = None


def fix_schema_with_pydantic(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fix an MCP tool schema using Pydantic to ensure it's compatible with Gemini.
    
    Args:
        schema: The original JSON schema from the MCP server
        
    Returns:
        A fixed schema compatible with Gemini
    """
    # Handle null/empty schema
    if not schema:
        return {"type": "object", "properties": {}}
    
    # Remove $schema field which causes issues with Gemini
    if "$schema" in schema:
        del schema["$schema"]
    
    # Remove additionalProperties which Gemini doesn't support
    if "additionalProperties" in schema:
        del schema["additionalProperties"]
    
    # Ensure schema has a type field
    if "type" not in schema:
        schema["type"] = "object"
    
    # Fix properties if they exist
    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_value in schema["properties"].items():
            # Ensure each property has a type
            if isinstance(prop_value, dict) and "type" not in prop_value:
                prop_value["type"] = "string"
            
            # Fix array types with missing items field
            if isinstance(prop_value, dict) and prop_value.get("type") == "array" and "items" not in prop_value:
                prop_value["items"] = {"type": "string"}
    
    return schema


def process_mcp_tools(tools: List[Any]) -> List[Any]:
    """
    Process a list of MCP tools to make them compatible with Gemini.
    
    Args:
        tools: List of MCP tool objects
        
    Returns:
        List of processed tool objects with fixed schemas
    """
    processed_tools = []
    
    for tool in tools:
        # Create a copy to avoid modifying the original
        processed_tool = tool.copy() if hasattr(tool, "copy") else tool
        
        # Fix input schema if it exists
        if hasattr(processed_tool, "inputSchema") and processed_tool.inputSchema:
            processed_tool.inputSchema = fix_schema_with_pydantic(processed_tool.inputSchema)
        
        processed_tools.append(processed_tool)
    
    return processed_tools


def convert_to_pydantic_model(schema: Dict[str, Any]) -> BaseModel:
    """
    Convert a JSON schema to a Pydantic model.
    
    Args:
        schema: The JSON schema to convert
        
    Returns:
        A dynamically created Pydantic model based on the schema
    """
    if not schema or "properties" not in schema:
        return create_model("EmptyModel", __base__=BaseModel)
    
    field_definitions = {}
    
    for prop_name, prop_schema in schema["properties"].items():
        field_type = str  # Default type
        field_kwargs = {}
        
        if "description" in prop_schema:
            field_kwargs["description"] = prop_schema["description"]
        
        if "default" in prop_schema:
            field_kwargs["default"] = prop_schema["default"]
        
        if "type" in prop_schema:
            if prop_schema["type"] == "string":
                field_type = str
            elif prop_schema["type"] == "integer":
                field_type = int
            elif prop_schema["type"] == "number":
                field_type = float
            elif prop_schema["type"] == "boolean":
                field_type = bool
            elif prop_schema["type"] == "array":
                if "items" in prop_schema:
                    items_type = prop_schema["items"].get("type", "string")
                    if items_type == "string":
                        field_type = List[str]
                    elif items_type == "integer":
                        field_type = List[int]
                    elif items_type == "number":
                        field_type = List[float]
                    elif items_type == "boolean":
                        field_type = List[bool]
                    else:
                        field_type = List[Any]
                else:
                    # Add items type for arrays without it
                    field_type = List[str]
            elif prop_schema["type"] == "object":
                if "properties" in prop_schema:
                    # Recursively create nested models
                    field_type = convert_to_pydantic_model(prop_schema)
                else:
                    field_type = Dict[str, Any]
        
        # Set required or optional
        if "required" in schema and prop_name in schema["required"]:
            field_definitions[prop_name] = (field_type, Field(**field_kwargs))
        else:
            field_definitions[prop_name] = (Optional[field_type], Field(default=None, **field_kwargs))
    
    model_name = schema.get("title", "DynamicModel")
    dynamic_model = create_model(model_name, **field_definitions)
    
    return dynamic_model


def schema_from_pydantic_model(model: BaseModel) -> Dict[str, Any]:
    """
    Convert a Pydantic model back to a JSON schema that's compatible with Gemini.
    
    Args:
        model: The Pydantic model to convert
        
    Returns:
        A JSON schema compatible with Gemini
    """
    schema = model.model_json_schema()
    
    # Clean up the schema to make it Gemini-compatible
    if "$schema" in schema:
        del schema["$schema"]
    
    if "$defs" in schema:
        del schema["$defs"]
    
    # Recursively process nested schemas
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            if isinstance(prop_schema, dict):
                if "$ref" in prop_schema:
                    # Replace $ref with actual schema
                    del prop_schema["$ref"]
                    prop_schema["type"] = "object"
                
                # Ensure array items have type
                if prop_schema.get("type") == "array" and "items" in prop_schema:
                    if "$ref" in prop_schema["items"]:
                        del prop_schema["items"]["$ref"]
                        prop_schema["items"]["type"] = "object"
    
    return schema