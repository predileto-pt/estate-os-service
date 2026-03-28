import json
from typing import Any, TypedDict

import structlog
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from applicant_screening.application.dtos import (
    AffordabilityResult,
    IdentityVerificationResult,
    IncomeVerificationResult,
    ScreeningAssessmentResult,
)
from applicant_screening.domain.models import Applicant, ExtractedData, RiskLevel, ScreeningReport

logger = structlog.get_logger()


class ScreeningState(TypedDict):
    applicant: dict[str, Any]
    extracted_data: list[dict[str, Any]]
    identity_result: dict[str, Any] | None
    income_result: dict[str, Any] | None
    affordability_result: dict[str, Any] | None
    final_result: dict[str, Any] | None


class LangChainScreeningAssessor:
    def __init__(self, openai_api_key: str) -> None:
        self._llm = ChatOpenAI(model="gpt-5.4", api_key=openai_api_key)  # type: ignore[arg-type]
        self._graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:  # type: ignore[type-arg]
        graph = StateGraph(ScreeningState)
        graph.add_node("verify_identity", self._verify_identity)
        graph.add_node("verify_income", self._verify_income)
        graph.add_node("assess_affordability", self._assess_affordability)
        graph.add_node("generate_report", self._generate_report)

        graph.set_entry_point("verify_identity")
        graph.add_edge("verify_identity", "verify_income")
        graph.add_edge("verify_income", "assess_affordability")
        graph.add_edge("assess_affordability", "generate_report")
        graph.add_edge("generate_report", END)

        return graph.compile()

    @staticmethod
    def _langfuse_config(
        *,
        trace_name: str,
        step_name: str,
        applicant_id: str,
        organization_id: str | None = None,
        form_request_id: str | None = None,
    ) -> dict[str, Any]:
        handler = LangfuseCallbackHandler()
        metadata: dict[str, Any] = {"applicant_id": applicant_id}
        if organization_id:
            metadata["langfuse_user_id"] = organization_id
        if form_request_id:
            metadata["langfuse_session_id"] = form_request_id
        metadata["langfuse_tags"] = ["screening", step_name]
        return {"callbacks": [handler], "run_name": step_name, "metadata": metadata}

    async def _verify_identity(self, state: ScreeningState) -> dict[str, Any]:
        chain = self._llm.with_structured_output(IdentityVerificationResult)
        applicant = state["applicant"]
        config = self._langfuse_config(
            trace_name="applicant-screening",
            step_name="verify_identity",
            applicant_id=applicant.get("id", ""),
            organization_id=applicant.get("organization_id"),
            form_request_id=applicant.get("form_request_id"),
        )

        id_extraction = None
        for item in state["extracted_data"]:
            if "id_extraction" in item:
                id_extraction = item["id_extraction"]
                break

        if id_extraction:
            classification = id_extraction.get("classification", {})
            extraction = id_extraction.get("extraction", {})
            doc_type = classification.get("document_type", "UNKNOWN")
            confidence = classification.get("confidence", 0)
            prompt = f"""Verify the identity of this applicant by comparing their provided \
information against the structured fields extracted from their ID document.

Applicant NIF (Portuguese Tax ID): {applicant["nif"]}
Applicant Name: {applicant["name"]}

ID Document Type: {doc_type} (confidence: {confidence:.2f})

Extracted fields from ID document:
{json.dumps(extraction, default=str, indent=2)}

Compare the applicant's NIF against any tax ID / NIF field in the extraction.
Compare the applicant's name against the name fields in the extraction.
Consider the confidence scores for each field when making your assessment.
Return whether identity is verified, NIF matches, name matches, and your reasoning."""
        else:
            extracted = json.dumps(state["extracted_data"], default=str)
            prompt = f"""Verify the identity of this applicant by checking their ID document.

Applicant NIF (Portuguese Tax ID): {applicant["nif"]}
Applicant Name: {applicant["name"]}

Extracted document data:
{extracted}

Check if the NIF and name in the ID document match the applicant's provided information.
Return whether identity is verified, NIF matches, name matches, and your reasoning."""

        result = await chain.ainvoke(prompt, config=config)  # type: ignore[arg-type]
        return {"identity_result": result.model_dump()}  # type: ignore[union-attr]

    async def _verify_income(self, state: ScreeningState) -> dict[str, Any]:
        chain = self._llm.with_structured_output(IncomeVerificationResult)
        applicant = state["applicant"]
        extracted = json.dumps(state["extracted_data"], default=str)
        config = self._langfuse_config(
            trace_name="applicant-screening",
            step_name="verify_income",
            applicant_id=applicant.get("id", ""),
            organization_id=applicant.get("organization_id"),
            form_request_id=applicant.get("form_request_id"),
        )

        result = await chain.ainvoke(
            f"""Verify the income of this applicant by checking their proof of income documents.

Applicant Name: {applicant["name"]}

Extracted document data:
{extracted}

Check if there are at least 3 sequential months of income proof, if the name matches,
and calculate the average monthly income.
Return whether income is verified, how many months were verified, the average monthly income,
whether the name is the same across documents, and your reasoning.""",
            config=config,  # type: ignore[arg-type]
        )
        return {"income_result": result.model_dump()}  # type: ignore[union-attr]

    async def _assess_affordability(self, state: ScreeningState) -> dict[str, Any]:
        chain = self._llm.with_structured_output(AffordabilityResult)
        applicant = state["applicant"]
        income_result = state["income_result"]
        avg_income = income_result["average_monthly_income"] if income_result else 0
        config = self._langfuse_config(
            trace_name="applicant-screening",
            step_name="assess_affordability",
            applicant_id=applicant.get("id", ""),
            organization_id=applicant.get("organization_id"),
            form_request_id=applicant.get("form_request_id"),
        )

        listing_type = applicant["listing_type"]
        if listing_type == "ARRENDAMENTO":
            monthly_obligation = applicant.get("monthly_rent", 0) or 0
        else:
            property_value = applicant.get("property_value", 0) or 0
            monthly_obligation = property_value / (40 * 12)

        result = await chain.ainvoke(
            f"""Assess the affordability for this applicant.

Average Monthly Income: {avg_income}
Monthly Obligation: {monthly_obligation}
Listing Type: {listing_type}

Calculate the DTI (Debt-to-Income) ratio as monthly_obligation / average_monthly_income.
The DTI must be <= 35% (0.35) to be considered affordable.
Return the DTI ratio, monthly obligation, whether it's affordable, and your reasoning.""",
            config=config,  # type: ignore[arg-type]
        )
        return {"affordability_result": result.model_dump()}  # type: ignore[union-attr]

    async def _generate_report(self, state: ScreeningState) -> dict[str, Any]:
        chain = self._llm.with_structured_output(ScreeningAssessmentResult)
        applicant = state["applicant"]
        identity = state["identity_result"] or {}
        income = state["income_result"] or {}
        affordability = state["affordability_result"] or {}
        config = self._langfuse_config(
            trace_name="applicant-screening",
            step_name="generate_report",
            applicant_id=applicant.get("id", ""),
            organization_id=applicant.get("organization_id"),
            form_request_id=applicant.get("form_request_id"),
        )

        result = await chain.ainvoke(
            f"""Generate a final screening assessment report based on these results:

Identity Verification: {json.dumps(identity)}
Income Verification: {json.dumps(income)}
Affordability Assessment: {json.dumps(affordability)}

Determine the overall risk level:
- LOW: All checks passed (identity verified, income verified, DTI <= 35%)
- MEDIUM: One check has concerns but no critical failures
- HIGH: Multiple checks failed or critical issues found

Provide a comprehensive justification for your risk assessment.""",
            config=config,  # type: ignore[arg-type]
        )
        return {"final_result": result.model_dump()}  # type: ignore[union-attr]

    async def assess(self, applicant: Applicant, extracted_data: list[ExtractedData]) -> ScreeningReport:
        initial_state: ScreeningState = {
            "applicant": {
                "id": str(applicant.id),
                "nif": applicant.nif,
                "name": applicant.name,
                "email": applicant.email,
                "organization_id": str(applicant.organization_id),
                "form_request_id": str(applicant.form_request_id),
                "listing_type": applicant.listing_type.value,
                "property_type": applicant.property_type.value if applicant.property_type else None,
                "property_value": applicant.property_value,
                "monthly_rent": applicant.monthly_rent,
            },
            "extracted_data": [ed.extracted_content for ed in extracted_data],
            "identity_result": None,
            "income_result": None,
            "affordability_result": None,
            "final_result": None,
        }

        langfuse_handler = LangfuseCallbackHandler()
        pipeline_metadata: dict[str, Any] = {
            "applicant_id": str(applicant.id),
            "langfuse_user_id": str(applicant.organization_id),
            "langfuse_session_id": str(applicant.form_request_id),
            "langfuse_tags": ["screening", "pipeline"],
        }

        result = await self._graph.ainvoke(
            initial_state,
            config={
                "callbacks": [langfuse_handler],
                "run_name": "screening_pipeline",
                "metadata": pipeline_metadata,
            },
        )
        final = result["final_result"]

        logger.info("screening_assessment_complete", risk_level=final["risk_level"])

        return ScreeningReport(
            applicant_id=applicant.id,
            risk_level=RiskLevel(final["risk_level"]),
            identity_verified=final["identity_verified"],
            income_verified=final["income_verified"],
            dti_ratio=final["dti_ratio"],
            justification=final["justification"],
            listing_type=applicant.listing_type,
            property_type=applicant.property_type,
            average_monthly_income=final["average_monthly_income"],
        )
