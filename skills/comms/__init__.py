"""Comms skills: WhatsApp handling, message outbox, drafts, translation, follow-ups, briefings.

``whatsapp_bot`` and ``send_message`` need a real provider (Twilio /
WhatsApp Business API) through their ``Protocol`` adapters and are
therefore ``local_only=False``; they never fake a send. ``chat_drafts``,
``translator``, ``followup_tracker`` and ``morning_briefing`` run fully
locally on the stdlib.
"""
