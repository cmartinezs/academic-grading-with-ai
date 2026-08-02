"""C3 email delivery JSON schemas for template, plan, and related documents."""

TEMPLATE_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/email-template-v1.json",
    "title": "Email Template V1",
    "type": "object",
    "required": [
        "schemaVersion", "templateId", "templateVersion",
        "intent", "subject", "textBody", "allowedPlaceholders"
    ],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"type": "string", "const": "1.0.0"},
        "templateId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
        "templateVersion": {"type": "string", "pattern": "^[1-9][0-9]*$"},
        "intent": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
        "subject": {"type": "string", "minLength": 1},
        "textBody": {"type": "string", "minLength": 1},
        "allowedPlaceholders": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9]*$"},
            "uniqueItems": True
        }
    }
}

PLAN_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/email-plan-v1.json",
    "title": "Email Plan V1",
    "type": "object",
    "required": [
        "schemaVersion", "planId", "sectionId", "publicationId",
        "snapshotContentHash", "snapshotReviewHash", "snapshotMode",
        "templateId", "templateVersion", "templateHash",
        "intent", "senderProfileId", "fromAddress",
        "recipientCount", "recipients", "previewHash"
    ],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"type": "string", "const": "1.0.0"},
        "planId": {"type": "string", "pattern": "^eplan_[0-9a-f]{24,}$"},
        "sectionId": {"type": "string"},
        "publicationId": {"type": "string"},
        "snapshotContentHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshotReviewHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshotMode": {"type": "string", "enum": ["legacy-effective", "grade-policy-effective"]},
        "templateId": {"type": "string"},
        "templateVersion": {"type": "string"},
        "templateHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "intent": {"type": "string"},
        "senderProfileId": {"type": "string"},
        "fromAddress": {"type": "string", "format": "email"},
        "replyTo": {"type": ["string", "null"], "format": "email"},
        "recipientCount": {"type": "integer", "minimum": 1},
        "recipients": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "studentId", "maskedRecipient",
                    "identityProjectionHash", "subject", "textBody",
                    "itemHash", "idempotencyKey"
                ],
                "additionalProperties": False,
                "properties": {
                    "studentId": {"type": "string"},
                    "maskedRecipient": {"type": "string"},
                    "identityProjectionHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "subject": {"type": "string", "minLength": 1},
                    "textBody": {"type": "string", "minLength": 1},
                    "itemHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "idempotencyKey": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                }
            }
        },
        "previewHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    }
}

SENDER_PROFILE_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/sender-profile-v1.json",
    "title": "Sender Profile V1",
    "type": "object",
    "required": ["schemaVersion", "senderProfileId", "fromAddress"],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"type": "string", "const": "1.0.0"},
        "senderProfileId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
        "fromAddress": {"type": "string", "format": "email"},
        "replyTo": {"type": "string", "format": "email"}
    }
}

STUDENT_EMAIL_VIEW_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/student-email-view-v1.json",
    "title": "Student Email View V1",
    "type": "object",
    "required": [
        "schemaVersion", "studentId", "sectionId",
        "publicationId", "snapshotMode", "assessments"
    ],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"type": "string", "const": "1.0.0"},
        "studentId": {"type": "string"},
        "sectionId": {"type": "string"},
        "publicationId": {"type": "string"},
        "snapshotMode": {"type": "string", "enum": ["legacy-effective", "grade-policy-effective"]},
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["assessmentId"],
                "properties": {
                    "assessmentId": {"type": "string"},
                    "assessmentLabel": {"type": "string"},
                    "status": {"type": "string"},
                    "score": {"type": ["string", "null"]},
                    "scoreUnit": {"type": "string"},
                    "grade": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "resultState": {"type": ["string", "null"]},
                    "finalizable": {"type": ["boolean", "null"]}
                }
            }
        }
    }
}

APPROVAL_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/email-approval-v1.json",
    "title": "Email Approval V1",
    "type": "object",
    "required": ["planId", "previewHash", "recipientCount", "approvedBy", "approvedAt", "status"],
    "additionalProperties": False,
    "properties": {
        "planId": {"type": "string"},
        "previewHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "recipientCount": {"type": "integer", "minimum": 1},
        "approvedBy": {"type": "string", "minLength": 1},
        "approvedAt": {"type": "string"},
        "status": {"type": "string", "const": "approved"}
    }
}

TRANSPORT_RECEIPT_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://academic-grading.ai/schemas/transport-receipt-v1.json",
    "title": "Transport Receipt V1",
    "type": "object",
    "required": ["accepted", "clientMessageId", "responseCode", "responseClass"],
    "additionalProperties": False,
    "properties": {
        "accepted": {"type": "boolean"},
        "providerMessageId": {"type": ["string", "null"]},
        "clientMessageId": {"type": "string"},
        "responseCode": {"type": "integer"},
        "responseClass": {"type": "string", "enum": ["accepted", "permanent-failure", "transient-failure", "unknown"]}
    }
}

ALL_SCHEMAS = {
    "email-template-v1": TEMPLATE_SCHEMA_V1,
    "email-plan-v1": PLAN_SCHEMA_V1,
    "sender-profile-v1": SENDER_PROFILE_SCHEMA_V1,
    "student-email-view-v1": STUDENT_EMAIL_VIEW_SCHEMA_V1,
    "email-approval-v1": APPROVAL_SCHEMA_V1,
    "transport-receipt-v1": TRANSPORT_RECEIPT_SCHEMA_V1,
}
