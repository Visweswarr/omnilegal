"""EUR-Lex SOAP/webservice adapter — delegates to the CELLAR REST adapter.

The EUR-Lex registered SOAP service (EURLexWebService) is used for document
search; bulk content retrieval goes through CELLAR SPARQL/REST. This module
re-exports the CELLAR adapter's fetch function so both adapter labels
("eurlex_soap" and "eurlex_cellar") resolve to the same implementation.

To use the SOAP search endpoint directly, replace with a SOAP-specific
implementation once SOAP credentials are provisioned.
"""
from __future__ import annotations

from src.services.adapters.eurlex_cellar import fetch  # noqa: F401  — re-export

__all__ = ["fetch"]
