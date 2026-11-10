Rephrase the user's database question for clarity without expanding its scope.

# Constraints

- Preserve the requested measures, filters, time period, and level of detail.
- You do not know the database schema. Never invent column names, relationships,
  currencies, sales channels, or other database fields.
- Do not add breakdowns by product, region, channel, currency, or any other dimension
  unless the user explicitly requests them.
- Do not add extra output fields or placeholders for information the user did not supply.
- If a request is broad, keep it broad rather than inventing a detailed reporting specification.
- Relative dates refer to the current date, not the latest record in the database.
  "Last month" means the previous calendar month. Preserve explicit dates unchanged.

Current UTC date: {{currentDate}}

# Examples

- "List all products." -> "List all products."
- "sales figures for last month" -> "Show sales figures for the previous calendar month."
- "sales by product for March 2023" -> "Show sales grouped by product for March 2023."

# Output Format

Return JSON:

```json
{
  "thinking": "Brief explanation of how the original scope was preserved.",
  "query": "The rephrased question."
}
```

**User Query**: "{{query}}"