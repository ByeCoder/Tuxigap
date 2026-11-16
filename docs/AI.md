# Add a helpful AI teammate

AI is optional. Your local moderation rules keep working without it, and every AI moderation flag stays in human review.

## Connect a provider

Fill in `.env`:

```dotenv
AI_API_KEY=YOUR_PRIVATE_KEY
AI_MODEL=YOUR_PROVIDER_MODEL
AI_BASE_URL=https://api.openai.com/v1
AI_DAILY_LIMIT=100
AI_USER_DAILY_LIMIT=10
```

Choose a model the provider actually offers. The adapter uses `POST /chat/completions`, `max_completion_tokens`, and JSON-object responses for structured reviews and quizzes. An OpenAI-compatible endpoint can point to another provider; there is no automatic provider failover or multi-model voting in the native core.

## Choose what your community shares

| Feature | Default | Data sent |
|---|---|---|
| Chat assistant | Off | The question, group rules and up to three relevant public notes |
| Recent context | 0 messages | When enabled: up to 20 recent visible message texts, bounded in size |
| Text moderation | Off | Message text, rules and recent labeled examples |
| Image review | Off | A downloaded photo, caption and rules; image download limited to 2 MiB |
| AI quiz | Admin-triggered | A topic and selected group language |
| Summary | Requires context | The bounded recent context and public reference notes |

Enable features from **AI & learning**. Language instructions follow the selected group language; the provider may still make mistakes.

Please tell your members about your configuration and provider. The core doesn't send voices or videos to AI. Provider storage and privacy policies are separate from local `/forget` behavior.

## Public-note knowledge

Create notes in **Content & scheduling**. The helper selects up to three notes with simple word overlap and sends them as reference data. This is a small community knowledge feature, not a vector database or full PDF/document RAG service. The optional Studio companion provides its own larger knowledge/CRM features.

## What “learning” means

- Admins label examples with `/spam`, `/ham` or feedback buttons.
- Local matching uses normalized text and conservative word-set similarity.
- Selected examples can provide context to AI moderation.
- If a real tg-spam engine is configured, feedback waits in a durable queue for that engine.
- Examples are isolated by group, capped at 500, and retained locally for up to 90 days.

This is human-guided matching and context, **not fine-tuning a foundation model** or reading an admin's unobserved intentions. Native manual deletions aren't all visible to a Bot API client. Explicit blocked-word/content rules aren't overruled by a safe-example label.

## Failure behavior and cost

AI responses are treated as untrusted data. JSON verdicts and confidence values are validated; the model has no moderation, payment or shell tools. Timeout, quota exhaustion or an invalid result leaves local protection running.

Quotas count requests per UTC day, per group and per member in that group. They are not a currency budget or global spending cap; images and different models can cost different amounts. Monitor your provider account and set its own billing controls as needed.

The native image reviewer is an opt-in capability inspired by the broader moderation goal; it is not a copy or a deployment of Shield's complete vision pipeline.
