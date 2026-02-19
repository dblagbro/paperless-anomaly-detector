"""Client for interacting with Paperless-ngx REST API."""
import logging
from typing import List, Dict, Optional, Any
import httpx
from datetime import datetime, timedelta

from config import settings

logger = logging.getLogger(__name__)


class PaperlessClient:
    """Client for Paperless-ngx API with token authentication."""

    def __init__(self):
        self.base_url = settings.paperless_api_base_url.rstrip('/')
        self.headers = {
            "Authorization": f"Token {settings.paperless_api_token}",
            "Content-Type": "application/json"
        }
        self.timeout = 30.0

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make HTTP request to Paperless API with error handling."""
        url = f"{self.base_url}{endpoint}"

        # Never log tokens
        safe_headers = {k: v for k, v in self.headers.items() if k.lower() != 'authorization'}
        logger.debug(f"{method} {url} (headers: {safe_headers})")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    **kwargs
                )
                response.raise_for_status()
                return response.json() if response.content else {}
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    def get_recent_documents(
        self,
        minutes: int = None,
        limit: int = None,
        ordering: str = "-created"
    ) -> List[Dict]:
        """
        Get documents from Paperless, paginating through all results.

        Args:
            minutes: Only fetch documents created in the last N minutes (None for all)
            limit: Maximum total documents to return (None = no limit, fetch all pages)
            ordering: Sort order (default: newest first)

        Returns:
            List of document dictionaries
        """
        page_size = 100  # Paperless default max page size
        params = {
            "page_size": page_size,
            "ordering": ordering,
            "page": 1,
        }

        if minutes:
            cutoff = datetime.utcnow() - timedelta(minutes=minutes)
            params["created__date__gte"] = cutoff.strftime("%Y-%m-%d")

        logger.info(f"Fetching documents from Paperless (limit={limit or 'all'})...")

        all_documents = []
        try:
            while True:
                response = self._make_request("GET", "/api/documents/", params=params)
                page_docs = response.get("results", [])
                all_documents.extend(page_docs)

                if limit and len(all_documents) >= limit:
                    all_documents = all_documents[:limit]
                    break

                next_url = response.get("next")
                if not next_url:
                    break

                params["page"] = params["page"] + 1

            logger.info(f"Fetched {len(all_documents)} documents total")
            return all_documents
        except Exception as e:
            logger.error(f"Failed to fetch documents: {e}")
            return all_documents  # return whatever was fetched before the error

    def get_document(self, doc_id: int) -> Optional[Dict]:
        """Get a single document by ID."""
        try:
            return self._make_request("GET", f"/api/documents/{doc_id}/")
        except Exception as e:
            logger.error(f"Failed to fetch document {doc_id}: {e}")
            return None

    def get_document_content(self, doc_id: int) -> Optional[str]:
        """Get the OCR text content of a document."""
        try:
            url = f"{self.base_url}/api/documents/{doc_id}/download/"
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=self.headers, params={"original": "false"})
                response.raise_for_status()

                # For now, just get the text content
                # In a production system, you'd parse the PDF and extract text
                doc = self.get_document(doc_id)
                return doc.get("content", "") if doc else None
        except Exception as e:
            logger.error(f"Failed to fetch content for document {doc_id}: {e}")
            return None

    def get_document_file(self, doc_id: int, archived: bool = True) -> Optional[bytes]:
        """
        Download the actual document file (PDF/image) for forensic analysis.

        Args:
            doc_id: Document ID
            archived: If True, get archived version; if False, get original

        Returns:
            File bytes or None if failed
        """
        try:
            url = f"{self.base_url}/api/documents/{doc_id}/download/"
            params = {"original": "false" if archived else "true"}

            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Failed to download file for document {doc_id}: {e}")
            return None

    def update_document_tags(self, doc_id: int, tag_ids: List[int]) -> bool:
        """Update document tags (replaces existing tags)."""
        try:
            data = {"tags": tag_ids}
            self._make_request("PATCH", f"/api/documents/{doc_id}/", json=data)
            logger.info(f"Updated tags for document {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update tags for document {doc_id}: {e}")
            return False

    def add_document_tags(self, doc_id: int, new_tag_names: List[str]) -> bool:
        """
        Add tags to a document without removing existing ones.
        Creates tags if they don't exist.
        """
        try:
            # Get current document to see existing tags
            doc = self.get_document(doc_id)
            if not doc:
                logger.error(f"Could not retrieve document {doc_id}")
                return False

            existing_tag_ids = set(doc.get("tags", []))
            logger.debug(f"Document {doc_id} existing tags: {existing_tag_ids}")

            # Get or create tags
            new_tag_ids = []
            for tag_name in new_tag_names:
                tag_id = self.get_or_create_tag(tag_name)
                if tag_id:
                    new_tag_ids.append(tag_id)
                    existing_tag_ids.add(tag_id)
                else:
                    logger.warning(f"Could not get/create tag '{tag_name}'")

            logger.info(f"Adding tags {new_tag_names} (IDs: {new_tag_ids}) to document {doc_id}")
            logger.debug(f"Final tag IDs to set: {list(existing_tag_ids)}")

            # Update document with all tags
            return self.update_document_tags(doc_id, list(existing_tag_ids))
        except Exception as e:
            logger.error(f"Failed to add tags to document {doc_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    # Legacy bare tag names written by pre-prefix versions of this code.
    # These are removed alongside anomaly:* tags on every sync.
    LEGACY_ANOMALY_TAG_NAMES = {
        'balance_mismatch', 'check_sequence_gap', 'layout_irregularity',
        'page_discontinuity', 'duplicate_lines', 'reversed_columns',
        'truncated_total', 'image_manipulation', 'detected',
    }

    def replace_document_anomaly_tags(self, doc_id: int, new_anomaly_tag_names: List[str]) -> bool:
        """
        Replace all anomaly tags on a document with the current detection results.
        Removes old anomaly:* tags AND legacy bare tag names, then adds new ones,
        preserving all unrelated tags.

        Args:
            doc_id: Document ID
            new_anomaly_tag_names: List of anomaly tag names to set (e.g., ['anomaly:balance_mismatch'])

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current document
            doc = self.get_document(doc_id)
            if not doc:
                logger.error(f"Could not retrieve document {doc_id}")
                return False

            # Get all current tags on document
            current_tag_ids = doc.get("tags", [])

            # Get all tag details to identify anomaly tags
            response = self._make_request("GET", "/api/tags/")
            all_tags = {tag["id"]: tag["name"] for tag in response.get("results", [])}

            # Strip both anomaly:* prefixed tags AND legacy bare tag names
            non_anomaly_tag_ids = [
                tag_id for tag_id in current_tag_ids
                if not all_tags.get(tag_id, "").startswith("anomaly:")
                and all_tags.get(tag_id, "") not in self.LEGACY_ANOMALY_TAG_NAMES
            ]

            logger.debug(f"Document {doc_id}: removing anomaly tags, keeping {len(non_anomaly_tag_ids)} non-anomaly tags")

            # Get or create new anomaly tags
            new_anomaly_tag_ids = []
            for tag_name in new_anomaly_tag_names:
                tag_id = self.get_or_create_tag(tag_name)
                if tag_id:
                    new_anomaly_tag_ids.append(tag_id)
                else:
                    logger.warning(f"Could not get/create tag '{tag_name}'")

            # Combine non-anomaly tags with new anomaly tags
            final_tag_ids = non_anomaly_tag_ids + new_anomaly_tag_ids

            logger.info(f"Replacing anomaly tags on document {doc_id}: {new_anomaly_tag_names} (IDs: {new_anomaly_tag_ids})")
            logger.debug(f"Final tag IDs: {final_tag_ids}")

            # Update document with final tag list
            return self.update_document_tags(doc_id, final_tag_ids)
        except Exception as e:
            logger.error(f"Failed to replace anomaly tags on document {doc_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def get_or_create_tag(self, tag_name: str) -> Optional[int]:
        """Get tag ID by name, creating it if it doesn't exist."""
        try:
            # Search for existing tag (Paperless returns partial matches, so we need exact match)
            response = self._make_request("GET", "/api/tags/", params={"name": tag_name})
            results = response.get("results", [])

            # Find exact match (API does partial matching)
            for tag in results:
                if tag["name"] == tag_name:
                    logger.debug(f"Found existing tag '{tag_name}' with ID {tag['id']}")
                    return tag["id"]

            # Create new tag if not found
            response = self._make_request("POST", "/api/tags/", json={"name": tag_name})
            logger.info(f"Created new tag: {tag_name} with ID {response.get('id')}")
            return response.get("id")
        except Exception as e:
            logger.error(f"Failed to get/create tag '{tag_name}': {e}")
            return None

    def get_or_create_custom_field(self, field_name: str, data_type: str = "string") -> Optional[int]:
        """Get custom field ID by name, creating it if it doesn't exist."""
        try:
            # Search for existing field
            response = self._make_request("GET", "/api/custom_fields/", params={"name": field_name})
            results = response.get("results", [])

            if results:
                return results[0]["id"]

            # Create new custom field
            field_data = {
                "name": field_name,
                "data_type": data_type  # string, integer, float, boolean, date, url
            }
            response = self._make_request("POST", "/api/custom_fields/", json=field_data)
            logger.info(f"Created new custom field: {field_name}")
            return response.get("id")
        except Exception as e:
            logger.error(f"Failed to get/create custom field '{field_name}': {e}")
            return None

    def set_custom_field(self, doc_id: int, field_name: str, value: Any, data_type: str = "string") -> bool:
        """Set a custom field value on a document."""
        try:
            field_id = self.get_or_create_custom_field(field_name, data_type)
            if not field_id:
                return False

            # Get current custom fields
            doc = self.get_document(doc_id)
            if not doc:
                return False

            custom_fields = doc.get("custom_fields", [])

            # Update or add the field value
            field_found = False
            for cf in custom_fields:
                if cf.get("field") == field_id:
                    cf["value"] = value
                    field_found = True
                    break

            if not field_found:
                custom_fields.append({"field": field_id, "value": value})

            # Update document
            self._make_request("PATCH", f"/api/documents/{doc_id}/", json={"custom_fields": custom_fields})
            logger.info(f"Set custom field '{field_name}' = '{value}' on document {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set custom field on document {doc_id}: {e}")
            return False

    def search_documents(self, query: str, limit: int = 100) -> List[Dict]:
        """Search documents using Paperless query syntax."""
        try:
            params = {"query": query, "page_size": limit}
            response = self._make_request("GET", "/api/documents/", params=params)
            return response.get("results", [])
        except Exception as e:
            logger.error(f"Failed to search documents: {e}")
            return []

    def get_or_create_document_type(self, type_name: str) -> Optional[int]:
        """
        Get document type ID by name, create if doesn't exist.

        Args:
            type_name: Name of the document type (e.g., "bank_statement", "invoice")

        Returns:
            Document type ID or None if failed
        """
        try:
            # Search for existing document type
            response = self._make_request("GET", "/api/document_types/")
            doc_types = response.get("results", [])

            # Format the type name for comparison
            formatted_name = type_name.replace("_", " ").title()

            for dt in doc_types:
                # Check both lowercase comparison and formatted name
                if dt["name"].lower() == type_name.lower() or dt["name"] == formatted_name:
                    logger.debug(f"Found existing document type: {dt['name']} (ID: {dt['id']})")
                    return dt["id"]

            # Create new document type if not found
            data = {
                "name": formatted_name,
                "match": "",
                "matching_algorithm": 0
            }
            response = self._make_request("POST", "/api/document_types/", json=data)
            logger.info(f"Created document type: {formatted_name} with ID {response['id']}")
            return response.get("id")

        except Exception as e:
            logger.error(f"Failed to get/create document type '{type_name}': {e}")
            return None

    def update_document_type(self, doc_id: int, doc_type_name: str) -> bool:
        """
        Update the document type for a document.

        Args:
            doc_id: Document ID
            doc_type_name: Name of the document type

        Returns:
            True if successful, False otherwise
        """
        try:
            type_id = self.get_or_create_document_type(doc_type_name)
            if not type_id:
                return False

            self._make_request("PATCH", f"/api/documents/{doc_id}/", json={"document_type": type_id})
            logger.info(f"Updated document {doc_id} type to '{doc_type_name}'")
            return True

        except Exception as e:
            logger.error(f"Failed to update document type for {doc_id}: {e}")
            return False
