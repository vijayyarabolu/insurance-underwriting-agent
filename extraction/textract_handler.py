"""
AWS Textract Document Extraction.

Extracts structured data from uploaded government IDs (Driver's License, Passport).
Uses the analyze_document API with FeatureTypes=["QUERIES"] for precise extraction.
"""

import boto3
import config

class TextractIDHandler:
    REQUIRED_FIELDS = [
        "FIRST_NAME",
        "LAST_NAME",
        "DOB",
        "ADDRESS",
        "ID_NUMBER",
        "EXPIRATION_DATE"
    ]
    QUERIES = [
        {'Text': 'What is the first name?', 'Alias': 'FIRST_NAME'},
        {'Text': 'What is the last name?', 'Alias': 'LAST_NAME'},
        {'Text': 'What is the date of birth?', 'Alias': 'DOB'},
        {'Text': 'What is the address?', 'Alias': 'ADDRESS'},
        {'Text': 'What is the document number?', 'Alias': 'ID_NUMBER'},
        {'Text': 'What is the expiration date?', 'Alias': 'EXPIRATION_DATE'},
        {'Text': 'What is the issue date?', 'Alias': 'ISSUE_DATE'},
        {'Text': 'What state issued this document?', 'Alias': 'ISSUING_STATE'}
    ]

    def __init__(self):
        if config.DEMO_MODE:
            self.client = None
            return

        try:
            self.client = boto3.client("textract", **config.aws_client_kwargs())
        except Exception:
            self.client = None
        
    def extract_id_data(self, document_bytes: bytes) -> dict:
        """
        Uses Textract to analyze a government ID and extract specific queried fields.
        """
        if not self.client:
            return self.fallback_data() if config.DEMO_MODE else {}

        try:
            # We use QUERIES to extract structured KV pairs reliably from IDs
            response = self.client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=['QUERIES'],
                QueriesConfig={
                    'Queries': self.QUERIES
                }
            )
            
            return self.parse_query_results(response)
        except Exception:
            return self.fallback_data() if config.DEMO_MODE else {}

    @staticmethod
    def fallback_data() -> dict:
        return {
            "FIRST_NAME": "Jane",
            "LAST_NAME": "Doe",
            "DOB": "1985-06-15",
            "ADDRESS": "123 Main St, Springfield, IL",
            "ID_NUMBER": "D12345678",
            "EXPIRATION_DATE": "2030-06-15",
            "ISSUE_DATE": "2024-06-15",
            "ISSUING_STATE": "IL"
        }

    @staticmethod
    def parse_query_results(response: dict) -> dict:
        """
        Maps Textract QUERY_RESULT blocks back to their QUERY aliases.

        Textract stores the alias on the parent QUERY block, while the extracted
        value lives on the related QUERY_RESULT block. The connection is the
        QUERY block's ANSWER relationship IDs.
        """
        blocks = response.get('Blocks', [])
        blocks_by_id = {
            block.get('Id'): block
            for block in blocks
            if block.get('Id')
        }
        answer_id_to_alias = {}

        for block in blocks:
            if block.get('BlockType') != 'QUERY':
                continue

            alias = block.get('Query', {}).get('Alias')
            if not alias:
                continue

            for relationship in block.get('Relationships', []):
                if relationship.get('Type') != 'ANSWER':
                    continue

                for answer_id in relationship.get('Ids', []):
                    answer_id_to_alias[answer_id] = alias

        extracted_data = {}
        for answer_id, alias in answer_id_to_alias.items():
            answer_block = blocks_by_id.get(answer_id, {})
            if answer_block.get('BlockType') != 'QUERY_RESULT':
                continue

            value = answer_block.get('Text')
            if value:
                extracted_data[alias] = value.strip()

        return extracted_data
