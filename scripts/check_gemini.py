"""Live check of only the committed synthetic invoice; never print extraction contents."""
import json
from pathlib import Path

from app.documents import parse_pdf
from app.extraction import AIAdapter, InvalidProviderResponse, ProviderError


def main():
    data = (Path(__file__).resolve().parents[1] / "fixtures/native_invoice.pdf").read_bytes()
    validation = {"pydantic_validated": None, "evidence_validated": None}
    try:
        result = AIAdapter("gemini").extract(parse_pdf(data))
        validation.update(pydantic_validated=True, evidence_validated=True)
        if result.invoice.invoice_number != "SYN-001" or result.invoice.total != "400.00":
            raise InvalidProviderResponse("Synthetic fixture expectations were not met", validation_stage="fixture_expectation")
    except ProviderError as error:
        stage = getattr(error, "validation_stage", None)
        if stage == "evidence":
            validation.update(pydantic_validated=True, evidence_validated=False)
        elif stage == "pydantic":
            validation.update(pydantic_validated=False)
        print(json.dumps({"provider": "gemini", "status": "failed", **validation,
                          **error.details(), "message": str(error)}))
        return 1
    print(json.dumps({"provider": "gemini", "status": "passed", "pydantic_validated": True,
                      "evidence_validated": True, "evidence_count": len(result.evidence)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
