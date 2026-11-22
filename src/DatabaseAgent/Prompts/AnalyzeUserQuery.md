Analyze the user's database question without rewriting it.

# Outcomes

Return exactly one outcome:

- `preserve`: the question is clear and can be used as written.
- `normalize`: the intended request is clear, but wording such as a relative
  date can be safely normalized without inventing scope or business definitions.
- `clarify`: a required business definition, filter, measure, date, or scope is
  missing or has multiple valid interpretations.

Do not choose a business definition silently. Do not produce a rewritten query.
Provide guidance for the separate rewrite step only.

# Rules

- Preserve the requested measures, filters, time period, and level of detail.
- Relative dates refer to the current UTC date, not the latest database record.
- Use `clarify` for terms such as "active" when the business meaning is not
  supplied.
- Use `normalize` only when the intended interpretation is safe and explicit.
- If clarification context is provided, use it to reassess the original request.

# Output format

Return JSON:

```json
{
  "outcome": "preserve | normalize | clarify",
  "guidance": "Instructions for the separate rewrite step.",
  "clarification_question": "A concise question for the user, if outcome is clarify."
}
```

Current UTC date: {{currentDate}}

Original user question:
{{query}}

Clarification supplied in this request, if any:
{{clarification}}
