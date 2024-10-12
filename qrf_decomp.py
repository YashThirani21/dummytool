from anytool.api_database_function import *
import json
import os
from anytool.prompt_template import *
from anytool.verifier import check_task_solvable_by_function, check_task_solvable, check_rewrite_validity_verifier, combine_into_final_answer_function, check_rewrite_quality, check_solved_toolbench, check_solved_toolbench_rewrite, check_solved_toolbench_decompose, check_task_complete
from termcolor import colored
from openai_utils import call_gpt
import threading
from threading import Thread, Semaphore
import time
import numpy as np
from arguments import parse_args
args = parse_args()
output_dir = args.output_dir
raise_error = False
max_api_number = args.max_api_number
sem = Semaphore(16)
class DoNothingContextManager:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

leaf_tool_number = args.leaf_tool_number

# multi_thread = True
multi_thread = False

if multi_thread:
    counter_lock = threading.Lock()
else:
    counter_lock = DoNothingContextManager()
    
def Finish():
    """Finish the conversation"""
    return 'finished'

def remove_apis(api_list):
    """remove apis from the current available api list. required input to be list of dictionaries describing with the keys category_name, tool_name, api_name"""
    print(colored(f'removing apis: {api_list}', 'red'))
    if len(api_list) == 0:
        return 'empty api list'
    if isinstance(api_list, str):
        api_list = eval(api_list)
    if not isinstance(api_list, list) or any('category_name' not in ele or 'tool_name' not in ele or 'api_name' not in ele for ele in api_list):
        return 'illegal input, input should be list, each element in the list should have category_name, tool_name, api_name'
    if not all([isinstance(ele['category_name'],str) and isinstance(ele['tool_name'],str) and isinstance(ele['api_name'],str) for ele in api_list]):
        return 'illegal input, category_name, tool_name, api_name should be string'
    origin_api_list = deepcopy(api_list)
    # for api in origin_api_list:
    #     self.api_list.remove(api)
    global global_api_list, global_api_list_detailed
    for api in api_list:
        # api.update(get_api_details(api['category_name'], api['tool_name'], api['api_name']))
        tool_details = get_tool_description(api['category_name'], api['tool_name'])
        api_details = get_api_details(**api)
        api['tool_description'] = tool_details['tool_description'] if isinstance(tool_details, dict) else ''
        api['api_description'] = api_details['description'] if 'description' in api_details else ''
        try:
            with counter_lock:
                if api in global_api_list:
                    global_api_list.remove(api)
        except:
            pass

    for api in origin_api_list:
        for ele in global_api_list:
            if ele['category_name'] == api['category_name'] and ele['tool_name'] == api['tool_name'] and ele['api_name'] == api['api_name']:
                with counter_lock:
                    global_api_list.remove(ele)
                break
    return f'APIs removed successfully. Current API number: {len(global_api_list)}. Max API number: {max_api_number}'
def check_if_request_solvable_dummy(query, global_api_list_detailed):
        print('Inside check_if_request_solvable_dummy')
        global stop, status, total_tokens, call_cnt, solvable_flag
        if stop:
            return 'Current APIs already sufficient to solve the query.'
        t_s = time.time()
        solvable, reason, tokens = check_task_solvable_by_function(query, global_api_list_detailed)
        print(f'Solvable result: {solvable} - Reason: {reason}')
        total_tokens += tokens
        call_cnt += 1

        # if solvable == 'Solvable':
        #     solvable_flag += 1

        if solvable != 'Unsolvable':
            status = 'The current api list can solve the query.'
            
        else:
            status = f'The current API list cannot solve the query due to the following reason: {reason}'

def check_if_request_solvable_dummy2(query, global_api_list_detailed):
        print('Inside check_if_request_solvable_dummy2')
        global status, total_tokens, call_cnt, solvable_flag
        t_s = time.time()
        solvable, reason, tokens = check_task_solvable_by_function(query, global_api_list_detailed)
        print(f'Solvable result: {solvable} - Reason: {reason}')
        total_tokens += tokens
        call_cnt += 1

        if solvable == 'Solvable':
            solvable_flag += 1
        
        if solvable != 'Unsolvable':
            status = 'The current api list can solve the query.'
            
        else:
            status = f'The current API list cannot solve the query due to the following reason: {reason}'

def combine_into_final_answer(query, list_of_answers):
        print('Inside combine_into_final_answer')
        global status, total_tokens, call_cnt
        t_s = time.time()
        combined_answer, combine_reason, tokens = combine_into_final_answer_function(query, list_of_answers)
        total_tokens += tokens
        call_cnt += 1
        return combined_answer, combine_reason

class Agent(object):
    def __init__(self) -> None:
        print('Creating Agent')
        self.failed_reason = None
        self.messages = []
        self.depth = 0
        self.index = 0
        self.finish_search = False
        self.sub_agents = []
    
    def check_if_request_solvable(self): ### Added self here that previously wasn't
        global stop, status, total_tokens, call_cnt, temp_query
        if stop:
            return 'Current APIs already sufficient to solve the query.'
        t_s = time.time()
        solvable, reason, tokens = check_task_solvable_by_function(temp_query, global_api_list_detailed)
        total_tokens += tokens
        call_cnt += 1

        print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
        if solvable != 'Unsolvable':
            with counter_lock:
                stop = True
                status = 'The current API list can solve the query.'
            return f'Current API number: {len(global_api_list)}. Max API number: {max_api_number}'
        else:
            with counter_lock:
                status = f'The current API list cannot solve the query due to the following reason: {reason}'
            if len(global_api_list) >= max_api_number:
                with counter_lock:
                    stop = True
            return f'Current API number: {len(global_api_list)}. Max API number: {max_api_number}. The current API list cannot solve the query due to the following reason: {reason}'

class Category_Agent(Agent):
    def __init__(self, query, category=None) -> None:
        super().__init__()
        self.category = category
        self.tools = get_tools_in_category(self.category)
        self.query = query
        self.provisional_answer = None
        self.info = f'category: {self.category} assigned'
        self.api_mapping = {
                " ": query_all_categories,
                "retrieve_context": retrieve_context,
                "Finish": Finish,
                "get_tools_descriptions": get_tools_descriptions,
                "create_agent_tool_level": self.create_agent_tool_level,
                }
        self.functions = [
            get_tools_descriptions_function,
            finish_function,
            # retrieve_context_function
        ]
        self.tools = get_tools_in_category(self.category)
    
   
    def resume_search(self):
        """Assign a category to an agent"""
        global call_cnt, total_tokens, stop, error_flag 
        print(colored(f'resume_search Called', 'red'))
        if stop or total_tokens > 200000: 
            self.finish_search = True
            if multi_thread:
                sem.release()
            return f'category: {self.category} assigned'
        print(colored(f'assigning category: {self.category}', 'green'))
        if len(self.tools) <= leaf_tool_number:
            self.finish_search = True
            return f'category: {self.category} assigned'
        if self.failed_reason is not None:
            if self.provisional_answer is not None:
                self.messages.append({"role": "user", "content": REFIND_TOOL_PROMPT_WITH_ANSWER.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
                self.provisional_answer = None
            else:
                self.messages.append({"role": "user", "content": REFIND_TOOL_PROMPT_WITHOUT_ANSWER.replace('{failed_reason}', str(self.failed_reason))})
            self.failed_reason = None
            
        for k in range(20):
            print('Entered RS loop - Iteration: ', k+1)
            print(self.messages)
            if stop or total_tokens > 200000:
                if multi_thread:
                    sem.release()
                return f'category: {self.category} assigned'
            t_s = time.time()
            try:
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
            except:
                error_flag = True
                stop = True
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                continue
            tool_calls = response.choices[0].message.tool_calls
            print('Resume Category Thought:', response.choices[0].message.content)
            if tool_calls is not None:
                print('tool call number', len(tool_calls))
            # print('message', response.choices[0].message)
            if tool_calls:
                self.messages.append({
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    print('function call:', function_name, function_args)
                    if function_name == 'get_tools_in_category':
                        self.query_tools_call = True
                    if function_name.lower() == 'finish':
                        print(colored(f'category: {self.category} assigned and this agent is finished', 'green'))
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        self.finish_search = True
                        if multi_thread:
                            sem.release()
                            return f'category: {self.category} assigned.'
                        else:
                            return f'category: {self.category} assigned. The status of current found apis is: {status}'
                    elif function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                        self.messages.append(
                            {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_call_result),
                            }
                        )
                    else:
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = str(e)
                        self.messages.append(
                            {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_call_result),
                            })
                 
                    print('function response:', function_call_result)
            else:
                # continue
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        print(colored(f'category: {self.category} assigned', 'green'))
        self.finish_search = True
        if multi_thread:
            sem.release()
            return f'category: {self.category} assigned.'
        else:
            return f'category: {self.category} assigned. The status of current found apis is: {status}'
        
    def category_search(self):
        # This is where tools in a category are found (this function is called in 798 in create_agent_category_level)
        """Assign a category to an agent"""
        print(colored(f'Category Search Called', 'red'))
        print(colored(f'assigning category: {self.category}', 'green'))
        
        self.tools = get_tools_in_category(self.category)
        if len(self.tools) > leaf_tool_number:
            print('len(self.tools) > leaf_tool_number')
            self.functions.append(create_agent_tool_level_function)
            self.messages = [{
                "role": "system",
                "content": CATEGORY_AGENT_PROMPT.replace('{category}', self.category)},
                {"role": "user",
                 "content": f"Task description: {self.query}. All the tools: {self.tools}. Begin!"}]
        else:
            print('NOT len(self.tools) > leaf_tool_number')
            function_call_result = self.create_agent_tool_level(self.category, self.tools)
            return f'category: {self.category} assigned'
        global total_tokens, call_cnt, stop, error_flag
        for j in range(20):
            print('==========================')
            print(f'CS - iteration: {j+1} in category {self.category} with Stop {stop}')
            if (stop) or total_tokens > 200000:
                print(colored(f'Inside if category_search', 'red'))
                if multi_thread:
                    sem.release()
                    # Go to 775 now
                return f'category: {self.category} assigned'
            t_s = time.time()
            try:
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
            except:
                error_flag = True
                stop = True
                continue
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            tool_calls = response.choices[0].message.tool_calls
            print('CS Thought:', response.choices[0].message.content)
            if tool_calls is not None:
                print('tool call number', len(tool_calls))
            if tool_calls:
                self.messages.append(
                {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                }
                )
                for tool_call in tool_calls:
                        
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    # print('function call:', function_name, function_args)
                    if function_name.lower() == 'finish':
                        print(colored(f'category: {self.category} assigned and this agent is finished', 'green'))
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        self.finish_search = True
                        if multi_thread:
                            sem.release()
                            return f'category: {self.category} assigned.'
                        else:
                            return f'category: {self.category} assigned. The status of current found apis is: {status}'
                    elif function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                    else:
                        if function_name == "create_agent_tool_level":
                            print(colored('create_agent_tool_level', 'green')) 
                            print(colored(function_args, 'blue')) 
                            print(function_args) 
                        try:
                        # if True:
                            ########### create_agent_tool_level in 380 is called here
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            print('back from create_agent_tool_level')
                            if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                            
                            ########### Now go to 266
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = str(e)
                    self.messages.append(
                        {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": str(function_call_result),
                        })
                 
                    print('function response:', function_call_result)
            else:
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        print(colored(f'category: {self.category} assigned', 'green'))
        self.finish_search = True
        if multi_thread:
            sem.release()
            return f'category: {self.category} assigned.'
        else:
            return f'category: {self.category} assigned. The status of current found apis is: {status}'
    
    def create_agent_tool_level(self, category: str, tools):
        ########### coming from 344
        print(category)
        print(colored('Calling CAT in 362 with following tools'),'blue')
        print(tools)
        """Assign a subset of tools in a category to a agent"""
        if isinstance(tools, str):
            print('String tools provided')
            tools = eval(tools)
        illegal_tools = []
        for tool in tools:
            if tool not in self.tools:
                illegal_tools.append(tool)
        if len(illegal_tools) > 0:
            print(colored(f'Illegal tools: {illegal_tools} in category: {category} assigned', 'red'))
            return f'Illegal tools: {illegal_tools} in category: {category} assigned'
        if len(tools) > leaf_tool_number:
            return f'Tool number should not exceed the max tool number of {leaf_tool_number}. Please assign again'
        global tree
        with counter_lock:
            tree[category][str(tools)] = {}
        global agents, index
        with counter_lock:
            agents.append(Tool_Agent(self.query, category, tools))
            agents[-1].depth = self.depth + 1
            index += 1
            agents[-1].index = index
        self.sub_agents.append(agents[-1])
        # yield from agents[-1].tool_search()
        global threads
        if multi_thread:
            # Calling tool_search in line 612
            thread = threading.Thread(target=agents[-1].tool_search)
            sem.acquire()
            thread.start()
            ##### Coming from 605
            with counter_lock:
                threads.append(thread)
        else:
            agents[-1].tool_search()
        if multi_thread:
            # Go to 331 now
            return f'tools {tools} assigned.'
        else:
            return f'tools {tools} assigned. The status of current found apis is: {status}'
    
class Tool_Agent(Agent):
    def __init__(self, query, category=None, tools=None) -> None:
        super().__init__()
        self.category = category
        if isinstance(tools, str):
            tools = eval(tools)
        self.tools = tools
        self.functions = [finish_function]
        self.query = query
        self.provisional_answer = None
        if isinstance(tools, str):
            tools = eval(tools)
        if len(tools) > leaf_tool_number:
            return f"you should assign less than {leaf_tool_number} tools each time"
        else:
            self.functions.extend([
                # get_api_details_function,
                # get_apis_in_tool_function,
                # get_tool_details_function,
                check_if_request_solvable_function,
                # remove_apis_function,
                add_apis_into_api_pool_function,
            ])
            ### QATI being called
            tools_info = query_all_tool_info(category, tools)
            self.messages = [{
                "role": "system",
                "content": TOOL_AGENT_PROMPT.replace('{category}', str(category)).replace('{tools}', str(tools))},
                {"role": "user",
                 "content": f"Task description: {self.query} All the tool description and the contained api_list as a dict: {tools_info}. Begin!"}]
            
        self.api_mapping = {
                "query_all_categories": query_all_categories,
                "get_tools_in_category": get_tools_in_category,
                # "get_apis_in_tool": get_apis_in_tool,
                "Finish": Finish,
                # "get_api_details": get_api_details,
                "create_agent_tool_level": self.create_agent_tool_level,
                "add_apis_into_api_pool": self.add_apis_into_api_pool,
                "check_if_request_solvable": self.check_if_request_solvable,
                # "create_agent_query_reformulator": self.create_agent_query_reformulator,
                # "remove_apis": self.remove_apis,
                }
        
    def remove_apis(self, api_list):
        """remove apis from the current available api list. required input to be list of dictionaries describing with the keys category_name, tool_name, api_name"""
        print(colored(f'removing apis: {api_list}', 'red'))
        if isinstance(api_list, str):
            api_list = eval(api_list)
        if not isinstance(api_list, list) or any('category_name' not in ele or 'tool_name' not in ele or 'api_name' not in ele for ele in api_list):
            return 'illegal input, input should be list, each element in the list should have category_name, tool_name, api_name'
        if not all([isinstance(ele['category_name'],str) and isinstance(ele['tool_name'],str) and isinstance(ele['api_name'],str) for ele in api_list]):
            return 'illegal input, category_name, tool_name, api_name should be string'
        origin_api_list = deepcopy(api_list)
        global global_api_list, global_api_list_detailed
        for api in api_list:
            tool_details = get_tool_description(self.category, api['tool_name'])
            api_details = get_api_details(**api)
            api['tool_description'] = tool_details['tool_description'] if isinstance(tool_details, dict) else ''
            api['api_description'] = api_details['description'] if 'description' in api_details else ''
            try:
                with counter_lock:
                    if api in global_api_list:
                        global_api_list.remove(api)
            except:
                pass

        for api in origin_api_list:
            for ele in global_api_list:
                if ele['category_name'] == api['category_name'] and ele['tool_name'] == api['tool_name'] and ele['api_name'] == api['api_name']:
                    with counter_lock:
                        global_api_list.remove(ele)
                    break
        return f'apis removed successfully. Current api number: {len(global_api_list)}. Max api number: {max_api_number}'
    
    
    def create_agent_tool_level(self, category: str, tools):
        """Assign a subset of tools in a category to a agent"""
        if isinstance(tools, str):
            tools = eval(tools)
        illegal_tools = []
        for tool in tools:
            if tool not in self.tools:
                illegal_tools.append(tool)
        if len(illegal_tools) > 0:
            print(colored(f'Illegal tools: {illegal_tools} in category: {category} assigned', 'red'))    
            return f'Illegal tools: {illegal_tools} in category: {category} assigned'
        global tree
        with counter_lock:
            tree[category][str(tools)] = {}
        global agents, index
        with counter_lock:
            agents.append(Tool_Agent(self.query, category, tools))
            agents[-1].depth = self.depth + 1
            index += 1
            agents[-1].index = index
        self.sub_agents.append(agents[-1])
        # generator = agents[-1].tool_search()
        global threads
        if multi_thread:
            thread = threading.Thread(target=agents[-1].tool_search)
            sem.acquire()
            thread.start()
            with counter_lock:
                threads.append(thread)
        else:
            agents[-1].tool_search()
        if multi_thread:
            return f'tools {tools} assigned.'
        else:
            return f'tools {tools} assigned. The status of current found apis is: {status}'
    
    def add_apis_into_api_pool(self, api_list):
        # Coming from line 668
        """add apis to the current available api list. required input to be list of dictionaries describing with the keys category_name, tool_name, api_name"""
        print(colored(f'adding apis: {api_list}', 'red'))
        
        global global_api_list, global_api_list_detailed, stop, status
        ########## global_api_list initialized as null at the very top

        if len(global_api_list) + len(api_list) > max_api_number:
            return f'API number exceeds the max API number of {max_api_number}, current API number: {len(global_api_list)}, number of APIs to be added: {len(api_list)}. Please reduce the APIs to be added.'
        if isinstance(api_list, str):
            api_list = eval(api_list)
        # if len(api_list) > 2:
            # return 'too many apis to add, please add less than 2 apis each time'
        if not isinstance(api_list, list) or any('category_name' not in ele or 'tool_name' not in ele or 'api_name' not in ele for ele in api_list):
            return 'illegal input, input should be list, each element in the list should have category_name, tool_name, api_name'
        if not all([isinstance(ele['category_name'],str) and isinstance(ele['tool_name'],str) and isinstance(ele['api_name'],str) for ele in api_list]):
            return 'illegal input, category_name, tool_name, api_name should be string'
        # with counter_lock:
        #     for api in deepcopy(api_list):
        #         with counter_lock:
        #             if api not in global_api_list:
        #                 global_api_list.append(api)
        # if stop:
        #     return 'adding apis failed. Current apis already sufficient to solve the query. Please add again later.'
        # with counter_lock:
        for api in api_list:
            tool_details = get_tool_description(self.category, api['tool_name'])
            if tool_details == 'tool name not found':
                continue
            if api not in global_api_list:
                global_api_list.append(deepcopy(api))
            api_details = get_api_details(**api)
            api['tool_description'] = tool_details['tool_description'] if isinstance(tool_details, dict) else ''
            api['api_description'] = api_details['description'] if 'description' in api_details else ''
            if api not in global_api_list_detailed:
                global_api_list_detailed.append(api)
        print(f'Stop inside add_apis = {stop}')
        if not stop:
            t_s = time.time()
            # print(f'global_api_list_detailed: ', global_api_list_detailed)
            solvable, reason, tokens = check_task_solvable_by_function(self.query, global_api_list_detailed)
            print(f'Solvable - ', solvable, ' ; Reason - ', reason)
            #### verifier.py line 62
            global total_tokens, call_cnt
            total_tokens += tokens
            call_cnt += 1


            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if solvable != 'Unsolvable':
                stop = True
                status = 'The current api list can solve the query.'
                return f'APIs added. Current API number: {len(global_api_list)}. Max API number: {max_api_number}'
                # return 'apis added. The current api list can solve the query. If you think you have finished, call the Finish function.'
            else:
                status = f'The current API list cannot solve the query due to the following reason: {reason}'
                if len(global_api_list) >= max_api_number:
                    stop = True
                # return f'apis added. Current api number: {len(global_api_list)}. Max api number: {max_api_number}'
                return f'APIs added. Current API number: {len(global_api_list)}. Max API number: {max_api_number}.'
                # return f'apis added. Current api number: {len(global_api_list)}. Max api number: {max_api_number}. The current api list cannot solve the query due to the following reason: {reason} Please find apis more purposely.'
        return f'APIs added. Current API number: {len(global_api_list)}. Max API number: {max_api_number}'

    def resume_search(self):
        if stop or total_tokens > 200000: 
            self.finish_search = True
            if multi_thread:
                sem.release()
            print(f'tools {self.tools} assigned')
            return f'tools {self.tools} assigned'
        # self.functions.append(remove_apis_function)
        # self.functions.extend([
        #         create_agent_query_reformulator_function
        #     ])
        # if self.failed_reason is not None:
        #     if len(self.tools) > leaf_tool_number:
        #         self.messages.append({"role": "user", "content": REFIND_TOOL_PROMPT.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
        #     else:
        #         self.messages.append({"role": "user", "content": REFIND_API_PROMPT.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
        #     self.failed_reason = None
        if self.failed_reason is not None:
            if len(self.tools) > leaf_tool_number:
                if self.provisional_answer is not None:
                    self.messages.append({"role": "user", "content": REFIND_TOOL_PROMPT_WITH_ANSWER.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
                    self.provisional_answer = None
                else:
                    self.messages.append({"role": "user", "content": REFIND_TOOL_PROMPT_WITHOUT_ANSWER.replace('{failed_reason}', str(self.failed_reason))})
            else:
                if self.provisional_answer is not None:
                    self.messages.append({"role": "user", "content": REFIND_API_PROMPT_WITH_ANSWER.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
                    self.provisional_answer = None
                else:
                    self.messages.append({"role": "user", "content": REFIND_API_PROMPT_WITHOUT_ANSWER.replace('{failed_reason}', str(self.failed_reason))})
            self.failed_reason = None
        return self.tool_search()
    
    def tool_search(self):
        # Coming from line 412
        global stop, total_tokens, call_cnt, error_flag
        print(colored(f'Reviewing tools: {self.tools} in category: {self.category}', 'blue'))
        print("Inside tool_search")
        for p in range(20):
            print(f'ToolSearch iteration - {p+1} with stop: {stop}')
            if stop or total_tokens > 200000:
                print('#'*100)
                print(colored('stop', 'red'))
                if multi_thread:
                    sem.release()
                return f'tools {self.tools} assigned'
            t_s = time.time()
            try:
                # print('Calling GPT inside TOOL SEARCH')
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
                # print('Back from calling GPT inside TOOL SEARCH')
            except:
                print('Error calling GPT inside TOOL SEARCH')
                error_flag = True
                stop = True
                print('STOP SET TO TRUE')
                continue
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            tool_calls = response.choices[0].message.tool_calls
            print('Tool Call Thought: ', response.choices[0].message.content)
            if tool_calls is not None:
                print('tool call number', len(tool_calls))
            if tool_calls:
                # self.messages.append(response.choices[0].message)
                self.messages.append(
                {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                }
                )
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    print('TOOL SEARCH function call:', function_name, function_args)
            
                    if function_name.lower() == 'finish':
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        print(colored(f'tools {self.tools} assigned and this agent is finished searching', 'green'))
                        self.finish_search = True
                        if multi_thread:
                            sem.release()
                            return f'tools {self.tools} assigned'
                        else:
                            return f'tools {self.tools} assigned. The status of current found apis is: {status}'
                    if function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                    elif function_name == 'add_apis_into_api_pool':
                        print('Tool search calling add_apis_into_api_pool')
                        # Calling line 520
                        with counter_lock:
                            try:
                                ######## Calling line 520 add_apis_into_api_pool
                                function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                                ####### Now coming here with stop = True and global_api_list updated
                                ####### next go to line 600
                            except Exception as e:
                                print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                                if raise_error:
                                    raise e
                                function_call_result = 'input format error'
                    # elif function_name == 'create_agent_query_reformulator':
                    #     print('Tool search calling create_agent_query_reformulator')
                    #     # Calling line 520
                    #     try:
                    #         ######## Calling line 520 add_apis_into_api_pool
                    #         function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                    #         ####### Now coming here with stop = True and global_api_list updated
                    #         ####### next go to line 600
                    #     except Exception as e:
                    #         print(e)
                    #         print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                    #         if raise_error:
                    #             raise e
                    #         function_call_result = 'input format error'
                    else:
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = str(e)
                    self.messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(function_call_result),
                        })
                    print('function response:', function_call_result)
            else:
                # continue
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        print(f'tools {self.tools} assigned')
        self.finish_search = True
        if multi_thread:
            sem.release()
            ########## Now go to 392 again
            return f'tools {self.tools} assigned'
        else:
            return f'tools {self.tools} assigned. The status of current found apis is: {status}'
            
class Query_Reformulator_Agent(Agent):
    def __init__(self, query, reason, provisional_answer):
        print('Creating Query_Reformulator_Agent')
        print(colored(f'Reason: {reason}', 'yellow'))
        # print(f'provisional_answer: {provisional_answer}')
        super().__init__()
        global global_api_list        
        self.categories = []
        self.query = query
        self.solved = False
        self.provisional_answer = provisional_answer
        self.api_mapping = {
            "Finish": Finish,
            "rewrite_query": self.rewrite_query
            }
        
        self.functions = [
            rewrite_query_function,
            finish_function
            ]

        formatted_api_list = ""
        for i, api in enumerate(global_api_list):
            formatted_api_list += f"{i+1}. Category - {api['category_name']}, Tool - {api['tool_name']}, API - {api['api_name']}\n"

        
        
        self.messages = [{
            "role": "system",
            "content": QRF_AGENT_PROMPT_JUDGE_PARTS},
            {"role": "user",
             "content": f"Original query: {query} . \
             Provisional answer: {provisional_answer} . \
             Reason provided: {reason} . \
             Previously selected Tools and APIs: {formatted_api_list} . \
             Please call the rewrite_query function when you determine that the original query can be reworked. Begin!"}]
        

    # def judge_parts(self, query, answer, reason):
    #     print(colored(f'Inside judge_parts', 'green'))
    #     global rewrite_status, total_tokens, call_cnt
    #     rewrite_quality, rewrite_reason, tokens = check_unsolved_parts(self.query, answer, reason)
    #     print(f'Rewrite Quality: {rewrite_quality} - Reason: {rewrite_reason}')
    #     total_tokens += tokens
    #     call_cnt += 1
        
    #     if rewrite_quality == "True":
    #         rewrite_status = 'The rewrite is successful.'
    #     else:
    #         rewrite_status = f'The rewrite is not suitable due to the following reason: {reason}'
    #     return rewrite_quality, rewrite_reason
    
    def check_rewrite_validity(self, new_query):
        print(colored(f'Inside check_rewrite_validity', 'green'))
        global rewrite_status, total_tokens, call_cnt
        rewrite_quality, rewrite_reason, tokens = check_rewrite_validity_verifier(self.query, self.provisional_answer, new_query)
        print(f'Rewrite Quality: {rewrite_quality} - Reason: {rewrite_reason}')
        total_tokens += tokens
        call_cnt += 1
        
        if rewrite_quality == "True":
            rewrite_status = 'The rewrite is successful.'
        else:
            rewrite_status = f'The rewrite is not suitable due to the following reason: {reason}'
        return rewrite_quality, rewrite_reason
    
    def rewrite_query(self, rewritten_query):
        print(colored(f'Rewritten query: {rewritten_query}', 'green'))
        rewrite_quality, rewrite_reason = self.check_rewrite_validity(rewritten_query)
        global flag, stop, rewrite_cnt
        global global_api_list_detailed, global_api_list, temp_query, agents, messages
        print(colored(f'Stop value: {stop}', 'yellow'))
        if str(rewrite_quality) == "True":
            print(colored(f'Rewrite query success', 'green'))
            rewrite_cnt += 1
            flag = False
            stop = False
            global_api_list_detailed = []
            global_api_list = []
            temp_query = rewritten_query
            messages = None
            for agent in agents:
                if not agent.finish_search:
                    agent.query = rewritten_query
            new_runner = Main_Search_Agent(rewritten_query)
            agents.append(new_runner)
            if multi_thread:
                thread = threading.Thread(target=new_runner.assign_main, args=(rewritten_query,))
                print(colored(f'Threads', 'red'))
                print(threads)
                sem.acquire()
                thread.start()
                threads.append(thread)
            else:
                new_runner.assign_main(rewritten_query)
            return f'Rewrite success'
        else:
            print(colored(f'Rewrite failed due to : {rewrite_reason}', 'red'))
            return f'Rewrite failed due to {rewrite_reason} and original query retained'
    
    def resume_search(self):
        """Closing QRF"""
        global call_cnt, total_tokens, stop, error_flag 
        print(colored(f'called resume_QRF', 'red'))
        if stop or total_tokens > 200000: 
            print(f'Stop: {stop}')
            print(colored(f'QRF Resume IF', 'red'))
            self.finish_search = True
            if multi_thread:
                sem.release()
            return f'Closing QRF'
        print(colored(f'QRF Resume Else', 'red'))
        # if len(self.tools) <= leaf_tool_number:
        #     self.finish_search = True
        #     return f'Query Reformulator Finished Search'
        if self.failed_reason is not None:
            self.messages.append({"role": "user", "content": RESUME_QRF_PROMPT})
            self.failed_reason = None
        for m in range(20):
            print('Entered QRF loop - Iteration: ', m+1)
            print(self.messages)
            if stop or total_tokens > 200000:
                if multi_thread:
                    sem.release()
                return f'Query Reformulator Finished Search'
            t_s = time.time()
            try:
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
            except:
                error_flag = True
                stop = True
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                continue
            tool_calls = response.choices[0].message.tool_calls
            print('Resume QRFThought:', response.choices[0].message.content)
            if tool_calls is not None:
                print('tool call number', len(tool_calls))
            # print('message', response.choices[0].message)
            if tool_calls:
                self.messages.append({
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    print('function call:', function_name, function_args)
                    if function_name.lower() == 'finish':
                        print(colored(f'this agent is finished', 'green'))
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        self.finish_search = True
                        if multi_thread:
                            sem.release()
                            return f'Query Reformulator Finished Search'
                        else:
                            return f'Query Reformulator Finished Search'
                    elif function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                        self.messages.append(
                            {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_call_result),
                            }
                        )
                    else:
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = str(e)
                        self.messages.append(
                            {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_call_result),
                            })
                 
                    print('function response:', function_call_result)
            else:
                # continue
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        print(colored(f'category assigned', 'green'))
        self.finish_search = True
        if multi_thread:
            sem.release()
            return f'category assigned.'
        else:
            return f'category assigned. The status of current found apis is: {status}'
    
    def assign_qrf(self):
        global error_flag, stop, total_tokens, call_cnt, global_api_list
        try:
            # print('Messages in QRF Agent')
            # print(self.messages)
            response = call_gpt(
                            messages=self.messages,
                            functions=self.functions
                        )
        except:
            print('Error calling GPT inside TOOL SEARCH')
            error_flag = True
            stop = True
        print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
        
        with counter_lock:
            total_tokens += response.usage.total_tokens
            call_cnt += 1
        tool_calls = response.choices[0].message.tool_calls
        print('QRF Thought: ', response.choices[0].message.content)
        if tool_calls is not None:
            print('tool call number', len(tool_calls))
        if tool_calls:
            self.messages.append(
                {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                    }
                    )
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                print('QRF function call:', function_name, function_args)
        
                if function_name.lower() == 'finish':
                    self.messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": 'Finished',
                        })
                    print(colored('QRF finish', 'green'))
                    self.finish_search = True
                    if multi_thread:
                        sem.release()
                        return f'QRF completed'
                    else:
                        return f'QRF completed. The status of current found apis is: {status}'
                if function_name not in self.api_mapping:
                    function_name = 'hullucinating_function_name'
                    tool_call.function.name = function_name
                    function_call_result = "Function name error"
                elif function_name == 'rewrite_query':
                    print(colored(f'assign_qrf search calling rewrite_query', 'green'))
                    # Calling line 520
                    with counter_lock:
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            ####### Now coming here with stop = True and global_api_list updated
                            ####### next go to line 600
                        except Exception as e:
                            print(colored(f'ERROR calling rewrite_query', 'red'))
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = 'input format error'
                
                self.messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(function_call_result),
                    })
                print('function response:', function_call_result)
            else:
                # continue
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})

class Main_Search_Agent(Agent):
    def __init__(self, query) -> None:
        global call_cnt, total_tokens, temp_query
        print('Creating Main_Search_Agent')
        super().__init__()
        self.categories = []
        self.solved = False
        self.original_query = query
        self.provisional_answer = None
        self.api_mapping = {
    "query_all_categories": query_all_categories,
    "get_tools_in_category": get_tools_in_category,
    "get_apis_in_tool": get_apis_in_tool,
    # "retrieve_context": retrieve_context,
    "Finish": Finish,
    "get_api_details": get_api_details,
    # "locate_api": locate_api,
    # "query_tool_details": query_tool_details,
    "get_tools_descriptions": get_tools_descriptions,
    "create_agent_category_level": self.create_agent_category_level,
    "create_agent_query_reformulator": self.create_agent_query_reformulator,
    }
        self.functions = [
            # get_categories_function.to_json_schema(),
            # get_tools_in_category_function.to_json_schema(),
            # locate_api_function,
            get_tools_in_category_function,
            get_tools_descriptions_function,
            create_agent_category_level_function,
            # retrieve_context_function,
        ]
        self.functions.append(finish_function)

        if call_cnt == 0:
            new_query, tokens_decomp = decomposer_genie(query)
            print(f'Back from Decomposer with new_query: {new_query}')
            call_cnt += 1
            total_tokens += tokens_decomp
        else:
            new_query = query
        
        self.query = new_query
        temp_query = new_query
        
        self.messages = [{
            "role": "system",
            "content": META_AGENT_PROMPT.replace('{categories}', str(query_all_categories()))},
            {"role": "user",
             "content": f"Task description: {new_query}.\
             Please determine relevant categories and assign them use the create_agent_category_level function. Begin!"}]
        #  All the categories and the contained tools as a dictionary: {all_cates_all_tools}
            #  "content": f"Task description: {query}. All the categories as well as the contained tools and their descriptions: {category_tool_info}\
   
    def create_agent_category_level(self, category):
        """Assign a category to an agent"""
        # print(colored(f'assigning category: {category}', 'green'))
        #### coming here from 
        global agents, tree, index
        if category in self.categories:
            print(colored(f'category: {category} already assigned', 'green'))
            return f'category: {category} already assigned'
        with counter_lock:
            tree[category] = {}
        if not isinstance(category, str):
            return f'Error: category: {category} is not str'
        if category not in query_all_categories():
            return f'category: {category} not in database'
        self.categories.append(category)
        print(colored(f'CATEGORY: {category} ASSIGNED!', 'green'))
        with counter_lock:
            agents.append(Category_Agent(self.query, category))
            print('Category Agent created through Counter lock')
            index += 1
            agents[-1].depth = self.depth + 1
            agents[-1].index = index
        self.sub_agents.append(agents[-1])
        if multi_thread:
            # This is where category search of line 254 is called 
            thread = threading.Thread(target=agents[-1].category_search)
            sem.acquire()
            thread.start()
            with counter_lock:
                threads.append(thread)
        else:
            agents[-1].category_search()
        if multi_thread:
            ########## Back to 868
            return f'category: {category} assigned.'
        else:
            return f'category: {category} assigned. The status of current found apis is: {status}'

    def create_agent_query_reformulator(self, failed_reason, provisional_answer):
        global tree, agents, index, rewrite_cnt, all_answers
        if rewrite_cnt > 0:
            return f'Already reformulated once. Abandon new reformulation attempts.'
        with counter_lock:
            agents.append(Query_Reformulator_Agent(self.query, failed_reason, provisional_answer))
            agents[-1].depth = self.depth + 1
            index += 1
            agents[-1].index = index
        self.sub_agents.append(agents[-1])
        global threads
        if multi_thread:
            thread = threading.Thread(target=agents[-1].assign_qrf)
            sem.acquire()
            thread.start()
            with counter_lock:
                threads.append(thread)
        else:
            agents[-1].assign_qrf()
        if multi_thread:
            return f'QRF Activated.'
        else:
            return f'QRF Activated. The status is: {status}'
        
    def resume_search(self):
        global rewrite_cnt
        if stop or total_tokens > 200000: 
            self.finish_search = True
            if multi_thread:
                sem.release()
            return self.categories
        print(colored(f'Rewrite Cnt: {rewrite_cnt}', 'red'))
        
        if rewrite_cnt == 0:
            if create_agent_query_reformulator_function not in self.functions:
                self.functions.extend([create_agent_query_reformulator_function])
            if self.failed_reason is not None:
                self.messages.append({"role": "user", "content": REFIND_CATEGORY_PROMPT_BEFORE_REWRITE.replace('{failed_reason}', str(self.failed_reason)).replace('{provisional_answer}', str(self.provisional_answer))})
                self.failed_reason = None
        elif rewrite_cnt > 0:
            # print("self.functions")
            # print(self.functions)
            if create_agent_query_reformulator_function in self.functions:
                self.functions.remove(create_agent_query_reformulator_function)
            if self.failed_reason is not None:
                self.messages.append({"role": "user", "content": REFIND_CATEGORY_PROMPT_AFTER_REWRITE.replace('{failed_reason}', str(self.failed_reason))})
                self.failed_reason = None
        # return self.assign_main(self.query)
        # print(f'Restart main messages: {self.messages}')
        return self.restart_main()
    
    def restart_main(self):
        global stop, total_tokens, call_cnt, error_flag, global_api_list
        print("Inside restart_main")
        for l in range(20):
            if stop or total_tokens > 200000:
                print('#'*100)
                print(colored('stop', 'red'))
                if multi_thread:
                    sem.release()
                return f'Back from restart_main'
            t_s = time.time()
            try:
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
            except:
                print('Error calling GPT inside restart_main SEARCH')
                error_flag = True
                stop = True
                continue
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            tool_calls = response.choices[0].message.tool_calls
            print('restart_main Thought: ', response.choices[0].message.content)
            if tool_calls is not None:
                print('restart_main total tool calls: ', len(tool_calls))
            if tool_calls:
                # self.messages.append(response.choices[0].message)
                self.messages.append(
                {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                }
                )
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    print('MAIN RESTART function call:', function_name, function_args)
            
                    if function_name.lower() == 'finish':
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        print(f'tools assigned')
                        self.finish_search = True
                        if multi_thread:
                            sem.release()
                            return f'retart_main finished'
                        else:
                            return f'retart_main finished: {status}'
                    if function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                    elif function_name == 'create_agent_query_reformulator':
                        print(colored(('Main Restart qrf call'), 'green'))
                        # Calling line 520
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = 'input format error'
                    # elif function_name == 'create_agent_query_reformulator':
                    #     print('Tool search calling create_agent_query_reformulator')
                    #     # Calling line 520
                    #     try:
                    #         ######## Calling line 520 add_apis_into_api_pool
                    #         function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                    #         ####### Now coming here with stop = True and global_api_list updated
                    #         ####### next go to line 600
                    #     except Exception as e:
                    #         print(e)
                    #         print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                    #         if raise_error:
                    #             raise e
                    #         function_call_result = 'input format error'
                    else:
                        try:
                            function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                            if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                        except Exception as e:
                            print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                            if raise_error:
                                raise e
                            function_call_result = str(e)
                    self.messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(function_call_result),
                        })
                    print('function response inside restart_main:')
                    # print('function response inside restart_main:', function_call_result)
            else:
                # continue
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        print(f'restart main finished')
        self.finish_search = True
        if multi_thread:
            sem.release()
            ########## Now go to 392 again
            return f'restart main finished'
        else:
            return f'restart main finished. The status of current found apis is: {status}'

    def assign_main(self, query):
        print(colored(f'Provided query: {query}', 'green'))
        print(colored(f'assign_main with decomposed query: {self.query}', 'green'))
        global total_tokens, stop, error_flag, call_cnt, global_api_list, global_api_list_detailed
        # global query_to_process
        # query_to_process = query
        
        # TODO
        # self.query = query
        print(colored(f'Stop value in assign_main: {stop}', 'yellow'))
        print(colored(f'Total tokens: {total_tokens}', 'yellow'))
        ######### stop = False to start
        for i in range(20):
            print('==========================')
            print(f'Assign Main Iteration: {i+1} with stop value: {stop}')
            print('==========================')
            if stop or total_tokens > 200000:
                print(colored(f'Inside stop loop assign_main', 'red'))
                if multi_thread:
                    sem.release()
                ###### Coming from 864
                return self.categories
            t_s = time.time()
            print(colored(f'Else loop in assign_main', 'red'))
            try:
                response = call_gpt(
                                messages=self.messages,
                                functions=self.functions
                            )
            except:
                error_flag = True
                stop = True
                continue
            print(time.time() - t_s, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            if isinstance(response, str):
                print(response)
                print('response is str')
                continue
            with counter_lock:
                total_tokens += response.usage.total_tokens
                call_cnt += 1
            print('#'*100)
            tool_calls = response.choices[0].message.tool_calls
            print(colored(f'assign_main Thought: {response.choices[0].message.content}', 'yellow'))
            if tool_calls is not None:
                print('tool call number', len(tool_calls))
            if tool_calls:
                self.messages.append(
                {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                }
                )
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = tool_call.function.arguments
                    if function_name.lower() == 'finish':
                        self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": 'Finished',
                            })
                        self.finish_search = True
                        print(colored('main finish search', 'green'))
                        if multi_thread:
                            sem.release()
                        return self.categories
                
                    if function_name not in self.api_mapping:
                        function_name = 'hullucinating_function_name'
                        tool_call.function.name = function_name
                        function_call_result = "Function name error"
                    else:
                        if function_name == "retrieve_context" and 'query' not in function_args:
                            function_call_result = self.api_mapping[function_name](self.query, **json.loads(function_args))
                        else:
                            try:
                                # This is where create_agent_category_level is called. Look for 773 for next step.
                                function_call_result = self.api_mapping[function_name](**json.loads(function_args))
                                ###### Coming from 783
                                print(f'Got function call result in Iteration ',i+1)
                                ###### Go to 804
                                if function_name in ['get_apis_in_tool'] and isinstance(function_call_result, str) and 'Illegal tool' in function_call_result:
                                    function_call_result = f'Illegal tool. The tool should be in the tool list {self.tools}'
                            except Exception as e:
                                print(e, function_name, function_args, file=open(f'{output_dir}/error.txt', 'a', encoding='utf-8'))
                                if raise_error:
                                    raise e
                                function_call_result = str(e)
                    self.messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": str(function_call_result),
                            }
                        )
                    # print('function call:', function_name, function_args)
                    # print('function response:', function_call_result)
            else:
                self.messages.append({
                    "role": "assistant",
                    "content": response.choices[0].message.content if response.choices[0].message.content is not None else '',
                })
                self.messages.append({'role': "user",
                                 'content': 'At each step,  you should call a function to actually excute your step.'})
        
        
        self.finish_search = True
        if multi_thread:
            sem.release()
        print("self.categories")
        print(self.categories)

        print("************************")
        print(colored('Main_Search_Agent done', 'green'))
        
        return self.categories

create_agent_category_level_function = {
    'name': 'create_agent_category_level',
    'description': 'Assign a category to an agent',
    'parameters': {
        'type': 'object',
        'properties': {
            'category': {'type': 'string'}
        },
        'required': ['category']
    }
}

create_agent_tool_level_function = {
    'name': 'create_agent_tool_level',
    'description': 'Assign a subset of tools in a category to an agent',
    'parameters': {
        'type': 'object',
        'properties': {
            'category': {'type': 'string'}, 
            'tools': {
                'type': 'array', 
                'items': {'type': 'string'}
            }
        },
        'required': ['category', 'tools']
    }
}

create_agent_query_reformulator_function = {
    'name': 'create_agent_query_reformulator',
    'description': 'Reformulate the original query after incorporating both the feedback AND the provisional answer but do not contradict it',
    'parameters': {
        'type': 'object',
        'properties': {
            'failed_reason': {'type': 'string'},
            'provisional_answer': {'type': 'string'}
        },
        'required': ['failed_reason', 'provisional_answer']
    }
}
     
finish_function = {
                "name": "Finish",
                "description": "If you think you have finished, call this function.",
                "parameters": {
                    "type": "object",
                    'properties': {
                }
                }
}
import time
# from anytool.dfs_gt import solve_given_api_main, get_white_list
from anytool.dfs_gt import *
output_dir = args.output_dir
#### output_dir = result/anytoolbench

query_path = args.query_path
#### query_path = dummytoolbench.json

if __name__ == "__main__":
    os.makedirs(output_dir, exist_ok=True)
    #### output_dir = result/anytoolbench
    os.makedirs('output', exist_ok=True)
    success_cnt = 0
    unsolvable_task_cnt = 0
    unsolvable_list = json.load(open('misc/unsolvable.json', 'r', encoding='utf-8'))
    total_cnt = 0
    retrieval_cnt = 0
    rewrite_success_cnt = 0
    query_data_all = json.load(open(query_path, 'r', encoding='utf-8'))
    for query_data in query_data_all:
        try:
            
            print(f'Queries until now: {total_cnt}')
            print(f'Solved until now: {success_cnt}')
            if total_cnt > 0:
                solved_rate = round(100*success_cnt/total_cnt,1)
                print(f'Solved Rate until now: {solved_rate}')
                
                retrieval_rate = round(100*retrieval_cnt/total_cnt,1)
                print(f'Successful Retrievals until now: {retrieval_cnt} and {retrieval_rate} %')
            if success_cnt > 0:
                rewrite_success_rate = round(100*rewrite_success_cnt/total_cnt,1)
                print(f'Successful Rewrites until now: {rewrite_success_cnt} and {rewrite_success_rate} %')
            query_id = query_data['query_id']
            query = query_data['query']
            print('Query ID: ')
            print(query_id)
            print('Query to address: ')
            print(query)
            print("----------------------")
            threads = []
            global_api_list = []
            global_api_list_detailed = []   
            call_cnt = 0
            query_to_process = query
            temp_query = query
            rewrite_cnt = 0
            all_answers = []
            total_tokens = 0
            solve_tokens = 0
            agents = []
            index = 0
            failed_reason = None
            combined_answer = None
            temp_answer = None
            stop = False
            error_flag = False
            status = ''
            solved = False
            solvable_flag = 0
            check_solved = 'Unsolved'
            tree = {}
            result_list = []
            reason_list = []
            assign_results = {}
            assign_results['api_list'] = []
            assign_results['stop'] = []
            ts = time.time()
            resumed_agents = []
            if not args.include_unsolvable and int(query_id) in unsolvable_list:
                unsolvable_task_cnt += 1
                print(colored('Found in Unsolvable List', 'red'))
                print('Unsolvable human', unsolvable_task_cnt, success_cnt, total_cnt, file=open(f'{output_dir}/success_cnt.txt', 'a', encoding='utf-8'))
                continue
            total_cnt += 1
            task_solvable = 'Solvable'
            solvable_reason = 'Solvable checked by human'
            print("Checking existence of: ")
            print(f'{output_dir}/{query_id}.json')
            if os.path.exists(f'{output_dir}/{query_id}.json'):
                assign_results = json.load(open(f'{output_dir}/{query_id}.json', 'r', encoding='utf-8'))
                if 'last_solve_time' in assign_results:
                    solved = assign_results['solved']
                    check_solved = assign_results['check_solved']
                    last_solve_time = assign_results['last_solve_time']
                    if args.recheck_solved:
                        check_solved, reason, _ = check_solved_toolbench(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', assign_results['query_id'])
                        assign_results['check_solved'] = check_solved
                        assign_results['reason'] = reason
                        json.dump(assign_results, open(f'{output_dir}/{query_id}.json', 'w', encoding='utf-8'), indent=4)

                    api_list = assign_results['api_list'][-1]
                    api2origin = json.load(open(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', 'r', encoding='utf-8'))['api2origin']
                    if check_solved == 'Solved' and len(api_list) <= max_api_number:
                        success_cnt += 1
                    print(query_id, check_solved, unsolvable_task_cnt, success_cnt, total_cnt, success_cnt/total_cnt)
                    if assign_results['result'] != 'Timeout':
                        continue
                # continue
            # else:
            #     print('No query_id.json')
            #     break
            flag = False
            runner = Main_Search_Agent(query)
            agents.append(runner)
            if multi_thread:
                print("Multi thread")
                thread = threading.Thread(target=runner.assign_main, args=(query,))
                sem.acquire()
                thread.start()
                threads.append(thread)
            else:
                print("Single thread")
                iter_func = runner.assign_main(query)
            messages = None
            cnt = 0
            solve_data = {}
            if multi_thread:
                while True:
                    thread_num = len(threads)
                    # print("Number of threads: ")
                    # print(thread_num)
                    has_thread_alive = False
                    for thread in threads:
                        if thread.is_alive():
                            has_thread_alive = True
                            # print('Keeping main thread blocked until the existing thread is finished')
                            thread.join()
                    if not has_thread_alive:
                        break
                    if error_flag: raise Exception('GPT Call Error')
                threads = []
            # refind
            check_solved = ''
            max_depth = max([agent.depth for agent in agents])
            print(colored('ALL AGENTS', 'red'))
            print([agent for agent in agents])
            print([agent.finish_search for agent in agents])
            while not all([agent.finish_search for agent in agents]) or not flag:
                if check_solved == 'Solved':
                    break
                max_depth = max([agent.depth for agent in agents])  
                depth = max_depth
                while all([agent.finish_search for agent in agents if agent.depth == depth]) and depth >= 0:
                    depth -= 1
                if depth < 0 and flag:
                    break
                agents_to_resume = [agent for agent in agents if not agent.finish_search and agent.depth == depth and (not isinstance(agent, Main_Search_Agent))]
                main_agents = [agent for agent in agents if isinstance(agent, Main_Search_Agent)]
                if total_tokens > 200000 and flag:
                    solved = False
                    check_solved = 'Timeout'
                    solve_data = {'result': 'Timeout'}
                    break
                cnt += 1
                failed_reason = None
                print('#'*100)
                print(colored(('Global API List: '), 'blue'))
                print(global_api_list)
                print(len(global_api_list))
                print(f'Assign Results line')
                assign_results['api_list'].append(deepcopy(global_api_list))
                print(f'Stop value: {stop}')
                print(f'Flag value: {flag}')
                print([agent.finish_search for agent in agents])
                if stop or not flag or all([agent.finish_search for agent in agents]) and len(global_api_list) > 0:
                    # query = query_to_process
                    print(colored(('CHECKING SOLVABLE and sending to SOLVER: ', temp_query), 'yellow'))
                    flag = True
                    last_solve_time = cnt
                    t_s = time.time()
                    selected_api_list = deepcopy(global_api_list)
                    print(colored('FINAL SOLVABLE CHECK', 'green'))
                    check_if_request_solvable_dummy2(temp_query, selected_api_list)
                    
                    ### This is where the query is actually being solved after being given to solve_given_api_main: 
                    print(colored('Calling Solver', 'red'))
                    
                    tool_root_dir = "/Users/yashthirani/Desktop/ClonedRepos/ToolLLM/ToolBench/data/toolenv/tools"
                    tool_root_dir = extracted_folder_path_for_agg
                    print('Loading white list')
                    white_list = get_white_list(tool_root_dir)
                    
                    # solved, solve_data = solve_given_api_main(query, selected_api_list, f'{query_id}_{cnt}', white_list, messages)

                    ########## Sending the original query to the solver
                    solved, solve_data = solve_given_api_main(temp_query, selected_api_list, f'{query_id}_{cnt}', white_list, messages)
                    ############# Solve_Data contains the exact solution (more on this later)
                    print(colored(('BACK FROM SOLVER'), 'green'))
                    print(f'Rewrite_cnt: {rewrite_cnt}')
                    print('solve time:', time.time() - t_s, 'api number:', len(global_api_list),file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
                    result_list.append(deepcopy(solve_data['result']))
                    print(f'Solved value = {solved}')
                    if not solved or any([word in solve_data['result']['final_answer'] for word in exclusion_words]):
                        if solved:
                           print(colored(('Exclusion Words'), 'red'))
                        check_solved = 'Unsolved'
                        if 'reason' in solve_data['result']:
                            reason = solve_data['result']['reason']
                            # if 'final_answer' in solve_data['result']:
                            #     current_answer = solve_data['result']['final_answer']
                            # else:
                            #     current_answer = "No provisional answer was provided. "
                        elif 'final_answer' in solve_data['result']:
                            reason = "No reason provided. "
                            # current_answer = solve_data['result']['final_answer']
                            print(colored('No reason found, using provisional answer', 'red'))
                        else:
                            reason = "No reason for failure was generated in the previous attempt. "
                        print(colored((check_solved, reason), 'red'))
                    else:
                        ######### This is the block of code where self-reflection occurs. Check solved == Pass Rate
                        print(colored(('ENTERING SELF-REFLECTION'), 'green'))
                        if rewrite_cnt == 0:
                            # check_solved, reason, tokens = check_solved_toolbench(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', query_id, task_solvable, solvable_reason)
                            check_solved, reason, tokens = check_solved_toolbench_decompose(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', query_id, query_data['query'], task_solvable, solvable_reason)
                            total_tokens += tokens
                            print(colored((check_solved, reason), 'red'))

                    failed_reason = reason

                    if 'final_answer' in solve_data['result']:
                        provisional_answer = solve_data['result']['final_answer']
                        temp_answer = provisional_answer
                        print(colored('provisional answer', 'yellow'))
                        print(colored(temp_answer, 'yellow'))
                    else:
                        try:
                            provisional_answer = temp_answer
                            print(colored('No provisional answer was provided, reusing previous answer', 'red'))
                        except:
                            provisional_answer = "No provisional answer was provided in the previous attempt"
                            print(colored('No final answer found', 'red'))
                    all_answers.append(provisional_answer)
                    
                    #### Combining answers
                    combined_answer, combine_reason = combine_into_final_answer(query_data['query'], all_answers)

                    if rewrite_cnt > 0:
                        check_solved, reason, tokens = check_solved_toolbench_rewrite(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', query_id, query_data['query'], combined_answer, task_solvable, solvable_reason)
                        failed_reason = reason
                        total_tokens += tokens
                    
                    dfs_data = json.load(open(f'{output_dir}/{query_id}_{last_solve_time}_DFS_woFilter_w2.json', 'r', encoding='utf-8'))
                    total_tokens += dfs_data['answer_generation']['total_tokens']
                    solve_tokens += dfs_data['answer_generation']['total_tokens']
                    
                    if check_solved == 'Solved':
                        print(colored((f'Reason for success: {reason}'), 'green'))
                        for main_agent in agents:
                            if isinstance(main_agent, Main_Search_Agent) or isinstance(main_agent, Query_Reformulator_Agent):
                                main_agent.solved = True
                        # original_query = query_data['query']
                        # combined_answer, combine_reason = combine_into_final_answer(original_query, all_answers)
                        print(colored('Final Answer', 'blue'))
                        print(colored(combined_answer, 'green'))
                        print(query_data['query'], temp_query, combined_answer,  file=open(f'{output_dir}/success_answer_{query_id}.txt', 'a', encoding='utf-8'))
                        json.dump(combined_answer, open(f'{output_dir}/{query_id}_agent_tree.json', 'w', encoding='utf-8'), indent=4)   
                        break
                    else:
                        print(colored((f'Reason for failure: {reason}'), 'red'))
                    try:
                        messages = dfs_data['answer_generation']['train_messages'][-1]
                    except:
                        messages = None
                    api_list_to_prune = []
                    for standardized_api_name, origin_api in dfs_data['api2origin'].items():
                        if standardized_api_name in str(failed_reason):
                            if origin_api in global_api_list:
                                api_list_to_prune.append(origin_api)
                    
                    print(colored('api_list_to_prune', 'blue'))
                    print(colored(api_list_to_prune, 'red'))
                    remove_apis(api_list_to_prune)
                    if len(global_api_list) >= max_api_number:
                        break
                    stop = False
                else:
                    print(colored(('COULD NOT ENTER SOLVER'), 'red'))
                    print(f'Status: {status}')
                    assert status != 'The current api list can solve the query.'
                    failed_reason = status
                print(f'Failed reason: {failed_reason}')
                reason_list.append(failed_reason)
                print('Refind Begin for the following agents: ')
                print(agents_to_resume)
                print([agent.finish_search for agent in agents_to_resume])


                threads = []
                resume_cnt = 0 
                resumed_agents.append([(str(a), a.index) for a in agents_to_resume])
                for agent in reversed(agents_to_resume):
                    if agent.finish_search: continue
                    resume_cnt += 1
                    agent.failed_reason = str(failed_reason)
                    agent.provisional_answer = str(provisional_answer)
                    print(colored(('resuming: ', agent, agent.depth), 'red'))
                    print(colored(('resuming: ', agent, agent.depth), 'red'), file=open(f'{output_dir}/resume.txt', 'a', encoding='utf-8'))
                    print(colored(('Stop Value: ', stop), 'yellow'))
                    if multi_thread:
                        thread = threading.Thread(target=agent.resume_search)
                        sem.acquire()
                        thread.start()
                        threads.append(thread)
                    else:
                        agent.resume_search()
                print('Checking Main Agents')
                for agent in reversed(main_agents):
                    agent.failed_reason = str(failed_reason)
                    agent.provisional_answer = str(provisional_answer)
                    # all_answers.append(str(provisional_answer))
                    print(agent.solved)
                    if agent.solved == True:
                        continue
                    resume_cnt += 1
                    # agent.failed_reason = str(failed_reason)
                    # agent.provisional_answer = str(provisional_answer)
                    print(colored(('resuming: ', agent, agent.depth), 'red'))
                    print(colored(('resuming: ', agent, agent.depth), 'red'), file=open(f'{output_dir}/resume.txt', 'a', encoding='utf-8'))
                    print(colored((f'Stop Value: {stop}'), 'yellow'))
                    if multi_thread:
                        thread = threading.Thread(target=agent.resume_search)
                        sem.acquire()
                        thread.start()
                        threads.append(thread)
                    else:
                        agent.resume_search()
                if multi_thread:
                    while True:
                        thread_num = len(threads)
                        for thread in threads:
                            if thread.is_alive():
                                thread.join()
                        if thread_num == len(threads):
                            break
                        if error_flag: raise Exception('GPT Call Error')
                if not stop:
                    print('calling check_if_request_solvable_dummy AND stop = FALSE')
                    check_if_request_solvable_dummy(temp_query, global_api_list)
                    print(colored(f'status:{status}', 'red'))
                assign_results['stop'].append(stop)

            print(colored((f'Outside WHILE loop: Stop = {stop}'), 'green'))
            assign_results['api_complete'] = flag

            find_messages = []
            for agent in agents:
                find_messages.append([str(agent), agent.depth, agent.messages])
            assign_results['tree'] = tree
            assign_results['max_depth'] = max_depth
            assign_results['query'] = query_data['query']
            assign_results['find_messages'] = find_messages
            assign_results['status'] = status
            assign_results['solved'] = solved
            assign_results['query_id'] = query_id
            assign_results['finish_search'] = [agent.finish_search for agent in agents]
            assign_results['flag'] = flag
            
            if check_solved == 'Solved':
                success_cnt += 1
                if rewrite_cnt > 0:
                    rewrite_success_cnt += 1
                print(colored(f'Incrementing Pass to :{success_cnt}', 'green'))
            else:
                print(output_dir, 'failed', file=open(f'{output_dir}/failed.txt', 'a', encoding='utf-8'))
            
            if solvable_flag >= 1:
                retrieval_cnt += 1
                print(colored(f'Incrementing Retrieved to :{retrieval_cnt}', 'green'))
            
            assign_results['loop_times'] = cnt
            assign_results['last_solve_time'] = last_solve_time
            if 'messages' in solve_data:
                assign_results['solve_messages'] = solve_data['messages']
            def parse_tree(node, tree):
                tree[str(node)] = {}
                if (not isinstance(node, Main_Search_Agent)) and (not isinstance(node, Query_Reformulator_Agent)):
                    tree[str(node)]['category'] = node.category
                    tree[str(node)]['tools'] = len(node.tools)
                    tree[str(node)]['index'] = node.index
                tree[str(node)]['children'] = {}
                for agent in node.sub_agents:
                    tree[str(node)]['children'].update(parse_tree(agent, {}))
                return tree
            agent_tree = parse_tree(runner, {})
            tree_results = {}
            tree_results['agent_tree'] = agent_tree
            tree_results['resume_agents'] = resumed_agents  
            tree_results['result_list'] = result_list
            tree_results['reason_list'] = reason_list

            json.dump(tree_results, open(f'{output_dir}/{query_id}_agent_tree.json', 'w', encoding='utf-8'), indent=4)   
            assign_results['resume_agents'] = resumed_agents
            assign_results['result_list'] = result_list
            assign_results['reason'] = reason
            assign_results['reason_list'] = reason_list
            assign_results['call_cnt'] = call_cnt
            assign_results['total_tokens'] = total_tokens
            assign_results['solve_tokens'] = solve_tokens
            if 'result' in solve_data:
                assign_results['result'] = solve_data['result']
            assign_results['check_solved'] = check_solved
            json.dump(assign_results, open(f'{output_dir}/{query_id}.json', 'w', encoding='utf-8'), indent=4)

            #### Final solution
            print(check_solved, total_tokens, time.time() - ts, query_path, file=open(f'{output_dir}/time.txt', 'a', encoding='utf-8'))
            print(query_id, check_solved, success_cnt, total_cnt, success_cnt/total_cnt,  file=open(f'{output_dir}/success_cnt.txt', 'a', encoding='utf-8'))
        except Exception as e:
            print(f'Exception: {e}')
            continue
    solved_rate = round(100*success_cnt/total_cnt,1)
    retrieval_success_rate = round(100*retrieval_cnt/total_cnt,1)

    print(f'Total Queries: {total_cnt}')
    print(f'Total Retrieval: {retrieval_cnt}')
    print(f'Retrieved Rate: {retrieval_success_rate}')
    print(f'Total Solved: {success_cnt}')
    print(f'Solved Rate: {solved_rate}')
    print(f'Successful Rewrites: {rewrite_success_cnt}')