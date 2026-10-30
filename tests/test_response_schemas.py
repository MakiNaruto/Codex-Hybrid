import unittest

from pydantic import ValidationError

from adapters.response_schemas import (AdaptationSettings, AgentMessage, CustomArguments,
                                      CustomCall, CustomTool, StandaloneOutput)


class ResponseSchemaTests(unittest.TestCase):
    def test_configuration_defaults_are_independent_and_reject_unknown_fields(self):
        first, second = AdaptationSettings(), AdaptationSettings()
        first.adaptations.append('custom_tools')
        self.assertEqual(second.adaptations, [])
        for value in ({'adaptations':['guess']}, {'adaptations':['custom_tools']*2},
                      {'adaptations':'custom_tools'}, {'adaptations':None}, {'typo':True}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AdaptationSettings.model_validate(value)

    def test_native_extensions_survive_validation_without_inventing_required_data(self):
        data = {'type':'custom','name':'run','future_extension':{'enabled':True}}
        parsed = CustomTool.model_validate(data)
        self.assertEqual(parsed.model_dump(exclude_unset=True), data)
        for value in ({'type':'custom'}, {'type':'custom','name':123}):
            with self.assertRaises(ValidationError):
                CustomTool.model_validate(value)
        with self.assertRaises(ValidationError):
            CustomCall.model_validate({'type':'custom_tool_call','name':'run','input':'raw'})
        with self.assertRaises(ValidationError):
            StandaloneOutput.model_validate({'type':'function_call_output','name':'deliver'})

    def test_tool_wrapper_requires_complete_strict_json_without_extra_fields(self):
        for value in ('{"input":', '{"input":12}', '{"input":"ok","extra":1}', '{}'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CustomArguments.model_validate_json(value)
        self.assertEqual(CustomArguments.model_validate_json('{"input":"raw"}').input, 'raw')

    def test_agent_content_requires_plaintext_and_nonempty_content(self):
        for content in ([], [{'type':'input_text','text':123}],
                        [{'type':'encrypted_content','encrypted_content':'opaque'}]):
            with self.assertRaises(ValidationError):
                AgentMessage.model_validate({'type':'agent_message','content':content})

    def test_host_plaintext_in_encrypted_field_is_not_lost_or_mutated(self):
        import copy
        original = {'type':'agent_message','content':[
            {'type':'input_text','text':'Message Type: NEW_TASK'},
            {'type':'encrypted_content','encrypted_content':'Reply with PROBE_OK.'}]}
        before = copy.deepcopy(original)
        parsed = AgentMessage.model_validate(original)
        self.assertEqual(parsed.content[1].text,'Reply with PROBE_OK.')
        self.assertEqual(original,before)
        for value in ('gAAAAciphertext', 'opaque', '00000000-0000-0000-0000-000000000001-0'):
            with self.assertRaises(ValidationError):
                AgentMessage.model_validate({'type':'agent_message','content':[
                    {'type':'encrypted_content','encrypted_content':value}]})
