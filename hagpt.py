from ailib import Payload
from preferences import Preferences

from datetime import datetime
import requests
import json
import os
import re
import logging
import sys

# -- GPT Home Assistant wrapper over Payload, ChatHistoryManager, PromptBuilder, ModelConnection, Preferences --
class HAGPT:
    """
    Uses the Home Assistant services API and performs appropriate smart home operations, or just replies if request identified as a chat.
    Version 0.8.3
        - Changed virtual entity input_number.volume to mediaplayer.base to align better with the AI's training
    Version 0.8.2
        - Fixed bug that prevented gpt-5-mini from ever being used regardless of intelligence level setting
    Version 0.8.1
        - Added datetimestamps for chat history to give AI time context
    Version 0.8.0
        - Implemented Virtual Entities for AI to control Application Settings (debug, preferences default)
    Version 0.7.0
        - Implemented Preferences Class for settings and user preferences
    Version 0.6.0
        - Fixed preference issue with Chat History using raw responses
    """

    version = "0.8.3"
    ha_url = ""
    ha_entity_file = ""
    log_file = ""

    def __init__(self, preference_file: str):
       
        #Instantiate Settings/Prefs
        self.preferences = Preferences(preference_file)

        #Load up settings/preferences and then instantiate Payload with preferred config
        self.ha_url = self.preferences.get_setting_val("HA URL")
        self.base_url = self.preferences.get_setting_val("Base URL")
        self.ha_entity_file = self.preferences.get_setting_val("Entities File")
        prompts_file = self.preferences.get_setting_val("Prompts File")
        chat_hist_file = self.preferences.get_setting_val("Chat History File")
        self.log_file = self.preferences.get_setting_val("Log File")
        reasoning_eff = self.preferences.get_setting_val("Reasoning Effort") # Currently Not Implemented
        ai_intel_level = self.preferences.get_setting_val("AI Intel Level") # Currrently Not Implemented
        log_mode = self.preferences.get_setting_val("Log Mode")
        def_pref = self.preferences.get_setting_val("Default Preference")

        #Setup Log file and current mode (Debug or Info)
        self._configure_logging(log_mode)

        #Load Open AI Key and HA Token from environment variable
        api_key = self._load_openai_key()
        self.ha_token = self._load_ha_token()

        #Instantiate Payload with settings values retrieved
        self.payload = Payload(prompts_file, chat_hist_file, api_key)

    def _load_openai_key(self):

        api_key = os.getenv("OPENAI_API_KEY")

        if api_key is None:
            logging.error("OPENAI_API_KEY environment variable not found. An OpenAI API Key is required to run this application.")
            return ""

        else:
            return api_key
        
    def _load_ha_token(self):

        ha_token = os.getenv("HA_TOKEN")

        if ha_token is None:
            logging.error("HA_TOKEN environment variable not found. A Home Assistant Token is required to run this application.")
            return ""

        else:
            return ha_token

    def _configure_logging(self, log_mode: str):
        """Debug for DEBUG mode, Anything else for INFO"""
        
        #Default logging level set to Info but override to DEBUG with parameter
        log_level = logging.INFO

        if log_mode.lower() == "debug":
            log_level = logging.DEBUG

        logging.basicConfig(
            filename=self.log_file,
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
    def _clean_ai_response(self, ai_response):
        """
        Clean AI response and parse JSON for service, target, variables, and response_text.
        Assumes AI input is correct and formatted properly.
        """
        import json, re
        cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', ai_response.strip())
        cleaned = re.sub(r'\n?```$', '', cleaned.strip())

        try:
            data = json.loads(cleaned)
            service = data.get("service")
            target = data.get("target", {})
            variables = data.get("variables", {})
            response_text = data.get("response_text", "")
            dataopt = data.get("data",{})
        except json.JSONDecodeError:
            # Fallback: treat entire cleaned string as response_text
            service = None
            target = {}
            variables = {}
            dataopt = {}
            response_text = cleaned

        return {
            "service": service,
            "target": target,
            "variables": variables,
            "response_text": response_text,
            "data": dataopt 
        }

    def _call_ha_service(self, service, target=None, data=None, dataopt=None, variables=None):
        
        if target is None: target = {}
        if data is None: data = {}
        if dataopt is None: dataopt = {}
        if variables is None: variables = {}

        domain, service_name = service.split(".", 1)
        url = f"{self.ha_url}/api/services/{domain}/{service_name}"
        entity_id = target.get("entity_id")
        payload = {}

        #Setup payload depending on the HA Entity Type
        if service.startswith("script.") and variables:
            #Scripts
            payload = {"entity_id": entity_id, "variables": variables}
        elif service == "input_select.select_option" and data:
            #Process virtual devices and skip the HA update since they don't really exist
            if entity_id == "input_select.preferences":
                pref_sel = data.get("option")      
                self._set_virtual_file_entity(entity_id, pref_sel)
                return {"ha_result": "200: OK"}
            #All other real HA Input Select Entities (Intelligence Level)
            payload = {"entity_id": entity_id}
            payload.update(data)  
        elif service.startswith("notify.") and data:
            #Notify. Echo show uses it's own url format for notifications
            if service.startswith("notify.echo_"):
                payload = {"entity_id": entity_id}
                url = f"{self.ha_url}/api/services/{domain}/send_message"
            else:
                payload = {} # No entity for other notify services {"entity_id": entity_id}
            payload.update(data)  
        else:
            #Process virtual devices and skip the HA update since they don't really exist
            if entity_id == "switch.debug":
                self._set_virtual_file_entity(entity_id, service_name)
                return {"ha_result": "200: OK"}
            elif entity_id == "media_player.base_speaker" and data:
                #Set Volume Level value via Max Base Station API Call -> media_player.base_speaker
                vol_level_val = data.get("volume_level")
                logging.debug(f"AI Volume Level: {vol_level_val}")     
                ret_val = self._set_virtual_entity_base(entity_id, vol_level_val)
                return ret_val
        
            # All other real HA services (light.turn_on, switch.toggle, etc.)
            payload = {"entity_id": entity_id}
            payload.update(data)

        logging.debug(f"Final HA payload to send: {payload}")
        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json"
        }

        logging.info(f"HA API sending as: {url}")
        logging.info(f"HA API sending with: {payload}")
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                logging.error(f"HA ERROR {response.status_code}: {response.text}")
            else:
                logging.debug(f"HA HTTP response status: {response.status_code}, content: {response.text}")
            return {"ha_result": f"{response.status_code}: OK" if response.ok else f"{response.status_code}: {response.text}"}
        except requests.exceptions.RequestException as e:
            logging.error(f"HA service call failed: {e}")
            return {"ha_result": f"Request error: {str(e)}"}
    
    def _set_virtual_file_entity(self, virt_entity: str, virt_setting: str):
        
        # The AI will set these virtual entities on my command as if entities existed in HA.
        # The idea is to fool AI by adding switch.debug,etc as Entities in the entities file. 
        # We have modified _call_ha_service to intercept the virtual entities listed below
        # Virtual Entities here are made available via the HAGPT Settings/Preferences yaml file.
        setting_name = ""
        if virt_entity == "switch.debug":
            setting_name = "Log Mode"
            if virt_setting == "turn_on":
                setting_value = "Debug"
            else:
                setting_value = "Info"
        elif virt_entity == "input_select.preferences":
            setting_name = "Default Preference"
            setting_value = virt_setting
        else:
            logging.warning(f"Virtual Entity: {virt_entity} could not be set to '{virt_setting}', as it is not supported")
            return
        
        self.preferences.change_setting_val(setting_name,setting_value)
        set_val = self.preferences.get_setting_val(setting_name)
        logging.info(f"{setting_name} current setting value: {set_val}")        

    def _set_virtual_entity_base(self, virt_entity: str, virt_setting: str):
        """ For virt_entity, virt_setting example values: volume_level, 50"""
        
        # The AI will set these virtual entities on my command as if entities existed in HA.
        # The idea is to fool AI by adding media_player.base_speaker,etc as Entities in the entities file. 
        # We have modified _call_ha_service to intercept the virtual entities listed below
        # Virtual Entities here are available via the Home AI Max base API.

        payload = {}

        if virt_entity == "media_player.base_speaker":
            vol_setting = "level"
            try:
                vol_level = float(virt_setting) 
            except ValueError:
                logging.error(f"Could not convert vol_level: '{virt_setting}' to float")
                return {"ha_result": f"Request error: Volume_Float_Conversion"}
           
            payload = {"volume":{vol_setting: vol_level}}
            logging.debug(f"Max Virt Entity Payload: {payload}")

        max_url = f"{self.base_url}/control"
        headers = {"Content-Type": "application/json"}

        logging.info(f"Max API sending as: {max_url}")
        logging.info(f"Max API sending with: {payload}")

        try:
            response = requests.post(max_url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                logging.error(f"Max Base ERROR {response.status_code}: {response.text}")
            else:
                logging.debug(f"Max Base HTTP response status: {response.status_code}, content: {response.text}")
            return {"ha_result": f"{response.status_code}: OK" if response.ok else f"{response.status_code}: {response.text}"}
        except requests.exceptions.RequestException as e:
            logging.error(f"Max Base service call failed: {e}")
            return {"ha_result": f"Request error: {str(e)}"}

    def set_openAI_model(self, model: str):
        """One of 'gpt-5-mini', 'gpt-5-nano', 'gpt-4o-mini'"""

        #gpt-5* have low as valid value, gpt-4o-mini does not so set here and have else change to valid for 4
        #ModelConnection currently sets this as medium because of 4o issue.  Needs to be fixed so we can accept default here
        self.payload.connection.set_verbosity("low")

        if model == "gpt-5-mini":
            self.payload.connection.set_model("gpt-5-mini")
        elif model == "gpt-5-nano":
            self.payload.connection.set_model("gpt-5-nano")
        else:
            self.payload.connection.set_model("gpt-4o-mini")
            self.payload.connection.set_verbosity("medium")

    def get_ha_entity_info(self, input_file):
        """Retrieve current entity and state info from HA but only 
        for entities listed in the input_file."""

        if not input_file:
            raise ValueError("Usage: get_ha_entity_info(<entity_list_file>)")

        # Resolve file path relative to the script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        input_path = os.path.join(script_dir, input_file)

        try:
            with open(input_path, "r", encoding="utf-8") as f:
                entities = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            raise FileNotFoundError(f"Entity list file not found: {input_path}")

        # Build entity list: "switch.fan","switch.kettle",...
        entity_list = ",".join(f"\"{e}\"" for e in entities)

        # Build Jinja2 template same as Bash version
        template = (
            "{% for e in ["
            f"{entity_list}"
            "] %}{{ e }} ({{ state_attr(e, \"friendly_name\") or "
            "e.split('.')[1]|replace('_',' ')|title }}) state:{{ states(e) }}\\n{% endfor %}"
        )

        json_payload = json.dumps({"template": template})

        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }

        response = requests.post(f"{self.ha_url}/api/template", headers=headers, data=json_payload)

        if response.status_code != 200:
            raise RuntimeError(f"Error {response.status_code}: {response.text}")

        # Clean response text similar to sed: replace escaped newlines and extra spaces
        text = response.text.replace("\\n", "\n")
        text = " ".join(text.split())

        match = re.search(r'input_select\.intelligence_level.*?state:(\w+)', text)
        if match:
            intelligence_level = match.group(1)
            logging.debug(f"Intelligence level is set to HA Level: {intelligence_level}")  
            if intelligence_level == "High":
                self.set_openAI_model("gpt-5-mini")
            elif intelligence_level == "Medium":
                self.set_openAI_model("gpt-5-nano")
            else:
                self.set_openAI_model("gpt-4o-mini")

        else:
            intelligence_level = None


        return text

    def get_valid_preference_names(self):
        
        #Get valid user preference names.
        all_preferences = self.preferences.get_key_val(["User Prefs"])
        first_loop = True
        for preference_name in all_preferences:
            if not first_loop:
                pref_names = pref_names + ", " + preference_name
            else:
                pref_names = "Valid Preference Names (" + preference_name
                first_loop = False
        pref_names = pref_names + ")"

        return pref_names

    def process_ai_response(self, ai_response):
        """
        Process AI response and call Home Assistant service.
        Assumes AI input is correct and well-formed.
        """
        ha_result = None
        clean_response = self._clean_ai_response(ai_response)

        service = clean_response.get("service")
        target = clean_response.get("target", {})
        data = clean_response.get("data", {})
        dataopt = clean_response.get("dataopt", {})
        variables = clean_response.get("variables", {})
        response_text = clean_response.get("response_text", "")

        if service:
            ha_ret = self._call_ha_service(service, target, data, dataopt, variables)
            ha_result = ha_ret.get("ha_result")

            # Only process special entities if HA succeeded
            try:
                status_code = int(ha_result.split(":")[0])
            except (ValueError, IndexError):
                status_code = 0

            if 200 <= status_code < 300:
                entity_id = target.get("entity_id")

            else:
                logging.info(f"AI update failed: {ha_result}")

        return {
            "service": service,
            "target": target,
            "data": data,
            "dataopt": dataopt,
            "variables": variables,
            "response_text": response_text,
            "ha_result": ha_result
        }
        

# ============================================================= M A I N ==================================================

    def main(self):

        if len(sys.argv) < 2:
            print("Usage: python hagpt.py <MESSAGE_TO_AI>")
            return("<MESSAGE_TO_AI> parameter is required, HAGPT exiting")
            sys.exit(1)

        script = sys.argv[0]
        user_msg = sys.argv[1]

        logging.info("💡")
        logging.info(f"HAGPT v{self.version} class currently using ModelConnection v{self.payload.connection.version}, PromptBuilder v{self.payload.prompts.version}, ChatHistoryManager v{self.payload.history.version}, Preferences v{self.preferences.version}, Payload v{self.payload.version}")

        # This setting will be overriden when get_ha_entity_info retrieves HA's stored value 
        # but default here in case it is not successfully retrieved. We have this in settings now
        # but not sure if we will activate because a tool will be required for AI to change setting
        self.set_openAI_model("gpt-5-nano")
        
        self.payload.prompts.load_prompt("hagpt")
        self.payload.history.load_history("hagpt")

        #logging.info("!!!! History is currently being Reset for each interaction !!!!")
        #self.payload.history.reset_history()

        # Get Current Date formatted as 'Wednesday, Oct 01, 2025
        current_date = datetime.now().strftime('%A, %b %d, %Y')
        # Get Current Time formatted as '2:10 PM'
        current_time = datetime.now().strftime('%-I:%M %p')
        curr_date_time = f"Current Date: {current_date}  Current Time: {current_time} "

        # Load allowed HA entity info and states for the AI - Set Intelligence level after load
        entity_info = self.get_ha_entity_info(self.ha_entity_file)

        pref_names = self.get_valid_preference_names()
        logging.debug(f"Valid Preference Names: {pref_names}")

        logging.info(f"Model: {self.payload.connection.model}, Verbosity: {self.payload.connection.verbosity}, Reasoning: {self.payload.connection.reasoning_effort}, Max Tokens: {self.payload.connection.maximum_tokens}")

        # We have data to share with the AI. The current date/time, a list of HA Entities and their states 
        # as well as the default Preference and a list of valid preferences. It is not appropriate to add this
        # data to the prompt as AI's do not expect it there.
        special_user_role_content = f"{curr_date_time}., "
        special_user_role_content += f"Entity list and their current States: {entity_info}, "
        special_user_role_content += f"{pref_names}., "

        active_pref = self.preferences.get_active_preference()
        if len(active_pref) == 0:
            logging.info(f"No Active Preference is being added to prompt. Ensure a valid default is set.")
        else:
            special_user_role_content += f"Active -> {active_pref} "

        logging.debug(f"Special User Role Content: {special_user_role_content}")

        active_prompt = self.payload.prompts.get_prompt()

        logging.debug(f"Prompt Loaded: [{active_prompt}]")

        logging.info(f"User Message: [{user_msg}]")

        # We don't want to automatically add the AI response to chat history since it will be full of json
        # for the entities, devices, data, variables etc.  The important thing is to keep chat context
        # Therefore, we turn off auto, clean up response before logging both user/assistant messages to keep sync
        self.payload.Auto_Add_AI_Response_To_History = False

        # Send the user mesage to AI and receive the response
        reply = self.payload.send_message(user_msg, None, special_user_role_content)
        logging.info(f"Assistant Raw Reply: {reply}")
 
        ret = self.process_ai_response(reply)
        if ret:
            logging.debug(f"process_ai_response Full Return Value: {ret}")
            response_val = ret.get("response_text") or ""

        else:
            response_val = "AI response error, could not Process"
            logging.info(f"AI response error, return is: {ret}")

        # Adding current date/time to user message and reply in the chat history. This gives the AI some context relative to time so
        # it can distinguish between a conversation that is delayed a couple of seconds ago or a couple of days. Can be same date/time though.
        hist_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_msg_hist = f"[{hist_date_time}] {user_msg}"
        response_val_hist = f"[{hist_date_time}] {response_val}"

        # Since auto history is off, we can now add messages to history since processing went through 
        # without error. We hold back user_msg to keep chat history sync in case of error
        # self.payload.add_to_chat_history(user_msg, response_val)
        self.payload.add_to_chat_history(user_msg_hist, response_val_hist)

        logging.info(f"main() Returning (response_val): [{response_val}]")        


        return response_val


if __name__ == "__main__":

    # Change the current working directory to this script for imports and relative pathing
    program_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(program_path)

    wrapper = HAGPT("hagpt.json")

    ai_response = wrapper.main()
  
    print(f"{ai_response}")
    
    
