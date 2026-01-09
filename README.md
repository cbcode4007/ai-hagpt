## AI HAGPT Plugin

A small command-line program that uses AI to determine if an incoming message is a command or chat and responds in kind. It will attempt to carry out the commands according to the entities (devices/services) it is aware of, which requires some existing infrastructure, or carry the conversation for chat messages.

It takes the following parameters (besides the always necessary script name):
- User query string ("Can you turn the fan on?", "Hello!", etc.)
- Optionally, Log mode string ("info", the default, or "debug", for whether detailed debug lines are recorded in the log or just basic info)