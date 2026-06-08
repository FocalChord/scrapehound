"""Importing this package registers every adapter (via @register)."""
from . import (  # noqa: F401
    shopify, magento_graphql, jsonld, browser, embedded_json, apple,
)
