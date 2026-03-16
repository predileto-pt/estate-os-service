from property_management.application.ports.document_classifier import (
    ClassifiedDocument,
    DocumentClassifier,
)


class InMemoryDocumentClassifier(DocumentClassifier):
    async def classify(self, documents: list[bytes]) -> list[ClassifiedDocument]:
        result = []
        for i in range(len(documents)):
            if i == 0:
                result.append(
                    ClassifiedDocument(
                        index=i,
                        category="property_document",
                        document_subtype="escritura",
                    )
                )
            else:
                result.append(
                    ClassifiedDocument(
                        index=i,
                        category="personal_id",
                        document_subtype="cartao_cidadao",
                    )
                )
        return result
