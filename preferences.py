import json
from pathlib import Path


class Preferences:
    
    version = "0.0.1"  # Class attribute for version
        
    def __init__(self, preferences_file: str):
        self.preferences_file = Path(preferences_file)
        self._preferences = self._load_preferences()
        self._active_preference = ""
        self._combined = {}  # name -> text added
        #Now that we've loaded the Preferences/Settings file, let's carve out
        #get the default preference setting to load the active/selected preference
        pref = self.get_setting_val("Default Preference") or ""
        if pref:
            self.load_preference(pref)

    def _load_preferences(self) -> dict:
        if not self.preferences_file.exists():
            raise FileNotFoundError(f"Preferences file not found: {self.preferences_file}")
        with open(self.preferences_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_preferences_file(self):
            with open(self.preferences_file, "w", encoding="utf-8") as f:
                json.dump(self._preferences, f, indent=2, ensure_ascii=False)

    def load_preference(self, name: str):
        """Load a preference by name and set as active."""

        pref = self._preferences["User Prefs"].get(name)

        if pref:
            self._active_preference = pref
            self.active_preference_name = name
            self._combined.clear()

            return

        else:
            raise KeyError(f"Preference for '{name}' not found.")

    def get_setting_val(self, key):
        """ Get top level JSON key settings"""

        setting_val = self._preferences.get(key) or ""

        return setting_val

    def get_key_val(self, keys):
        """Gets all keys under key(s) hierarchy supplied 
        eg: ["User Prefs","Default","AI Interaction Prefs"] """
        data = self._preferences
        for key in keys:
            data = data.get(key, {})
        return data

    def add_to_preference(self, text: str):
        """Append arbitrary text to the current preference."""
        if text:
            self._active_preference += ("\n" if self._active_preference else "") + text

    def combine_preference(self, name: str):
        """Append a named preference to the active one."""
        if name not in self._preferences:
            raise KeyError(f"Preference '{name}' not found.")
        text = self._preferences[name]
        self._active_preference += ("\n" if self._active_preference else "") + text
        self._combined[name] = text

    def remove_preference(self, name: str):
        """Remove a previously combined named preference."""
        if name in self._combined:
            self._active_preference = self._active_preference.replace(self._combined[name], "").strip()
            del self._combined[name]

    def reset_preference(self, name: str = None):
        """Reset to empty or a named preference."""
        if name:
            self.load_preference(name)
        else:
            self._active_preference = ""
            self._combined.clear()

    def get_all_preferences(self):
        """Return the all settings/preferences on file as plain text."""
        return self._preferences
        
    def get_active_preference(self) -> str:
        """Return the current preference as plain text."""
        """Use this post reset, load, combine, add_to_preference"""
        return self._active_preference.strip()

    def change_setting_val(self, Setting_key: str,  SettingVal):
        """Change values for Setting keys in Prefs JSON"""

        self._preferences[Setting_key] = SettingVal
        self._save_preferences_file()