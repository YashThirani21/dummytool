import json
from anytool.prompt_template import *
from concurrent.futures import ThreadPoolExecutor,as_completed
from openai_utils import call_gpt
import time
from termcolor import colored
from arguments import parse_args
from anytool.check_solved import compute_pass_rate, process_invalid_data, process_valid_data
import os
from tqdm import tqdm
import random
args = parse_args()
output_dir = args.output_dir

def Finish(answer:str, reason:str=None):
    """Finish the conversation"""
    return answer, reason

def check_task_solvable(query):
    messages = [{
        "role": "system",
        "content": CHECK_SOLVABLE_PROMPT 
    },
        {"role": "user", 
        "content": f"Please check whether the following query is solvable: {query}. Begin!"}
        ]
    for i in range(5):
        response = call_gpt(
                        messages=messages,
                        functions=[solvable_finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print('Thought:', response.choices[0].message.content)
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                if function_name == 'Finish':
                    try:
                        solvable, reason = Finish(**json.loads(function_args))
                    except:
                        continue
                        # solvable, reason = Finish(json.loads(function_args))
                        
                else:
                    continue
                print(solvable, query, file=open('result/solvable.txt', 'a', encoding='utf-6'))
                if solvable == 'Unsolvable' and reason is None:
                    messages.append({"role": "user", "content": 'You must give reason if the answer is Unsolvable'})
                if reason is not None:
                    print(reason, file=open('result/solvable.txt', 'a', encoding='utf-8'))
                else:
                    reason = ''
                return solvable, reason
        else:
            print('Thought:', response.choices[0].message.content)
            continue
                # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
    print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    return 'No response', 'No response from the model'

def check_task_solvable_by_function(query, functions):
    messages = [{
        "role": "system",
        "content": CHECK_SOLVABLE_BY_FUNCTION_PROMPT 
    },
        {"role": "user", 
        "content": f"Query: {query}.  Available_tools: {functions}. You may begin!"}
        ]
    for i in range(2):
        response = call_gpt(
                        messages=messages,
                        functions=[solvable_finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print('Thought: chck_task_slvbl_fn', response.choices[0].message.content)
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                print(f'Function name in solvable: {function_name}')
                print(f'Function args in solvable: {function_args}')
                
                if function_name.lower() == 'finish':
                    try:
                        solvable, reason = Finish(**json.loads(function_args))
                    except:
                        continue
                        # solvable, reason = Finish(json.loads(function_args))
                else:
                    continue
                if solvable == 'Unsolvable' and reason is None:
                    messages.append({"role": "user", "content": 'You must give reason if the answer is Unsolvable'})
                if reason is None:
                    reason = ''
                print('Returning chck_task_slvbl_fn properly')
                return solvable, reason, response.usage.total_tokens
        else:
            print('Thought WITHOUT chck_task_slvbl_fn:', response.choices[0].message.content)
            if str(response.choices[0].message.content) == "Solvable":
                return "Solvable", "No reason"
            elif str(response.choices[0].message.content) == "solvable":
                return "Solvable", "No reason"
            content_dict = json.loads(response.choices[0].message.content)

            if 'answer' in content_dict:
                result_of_answer = content_dict['answer']
                if 'reason' in content_dict:
                    result_of_reason = content_dict['reason']
                    print(f'Returning answer: {result_of_answer} and reason: {result_of_reason}')
                    return result_of_answer, result_of_reason, response.usage.total_tokens
                else:
                    print(f'Returning answer: {result_of_answer} without reason')
                    return result_of_answer, "No reason provided", response.usage.total_tokens 
            else:
                continue
                # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
        # except:
        #     pass
    # print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    return 'Unsure', 'Connection to the assessing model timeout. You can call the check_current_api_suffucient function to check whether the current APIs is sufficient to solve the query.', response.usage.total_tokens

def combine_into_final_answer_function(query, list_of_answers):
    formatted_answer_list = ""
    count = 1
    for answer in list_of_answers:
        if answer != "No answer was generated in the previous attempt":
            formatted_answer_list += f"Answer {count}) - {answer} \n"
            count += 1

    messages = [
        {
        "role": "system",
        "content": COMBINE_INTO_ANSWER_PROMPT 
        },
        {"role": "user", 
        "content": f"Query: {query}. List of provisional answers: {formatted_answer_list}. Remember to call the finish function. Begin!"
        }
        ]
    
    print('Messages sent to combine')
    print(messages)
    for i in range(2):
        response = call_gpt(
                        messages=messages,
                        functions=[combine_finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print('Thought: cmbn_fnl_ans_fn', response.choices[0].message.content)
        print('============================')
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                print(f'Function name in combine: {function_name}')
                print(f'Function args in combine: {function_args}')
                if function_name.lower() == 'finish':
                    print('Calling finish in cmbn_fnl_ans_fn')
                    try:
                        combined_answer, reason = Finish(**json.loads(function_args))
                    except:
                        continue
                        # solvable, reason = Finish(json.loads(function_args))
                        
                else:
                    continue
                
                print('Returning cmbn_fnl_ans_fn properly')
                return combined_answer, reason, response.usage.total_tokens
        else:
            print('====================')
            print('Thought WITHOUT cmbn_fnl_ans_fn call: ', response.choices[0].message.content)
            continue
                # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
        # except:
        #     pass
    # print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    return formatted_answer_list, "Failed", response.usage.total_tokens


# def check_unsolved_parts(query, answer, reason):
#     messages = [
#         {
#         "role": "system",
#         "content": JUDGE_PARTS_PROMPT
#         },
#         {"role": "user", 
#         "content": f"Here is the original query: {query}. Here is the provisional solution in the first pass: {answer}. The reason provided for the failure is: {reason}. Begin!"
#         }
#         ]
#     for i in range(5):
#         response = call_gpt(
#                         messages=messages,
#                         functions=[check_unsolved_parts_function]
#                     )
#         tool_calls = response.choices[0].message.tool_calls
#         print(colored('Thought: rwrte_qlty_fin_fn', 'blue'))
#         print(response.choices[0].message.content)
#         print('=================================')
#         print('Now checking if tools are present')
#         if tool_calls:
#             for tool_call in tool_calls:
#                 function_name = tool_call.function.name
#                 print('function_name: ', function_name)
#                 function_args = tool_call.function.arguments
#                 print('function_args: ', function_args)
#                 if function_name.lower() == 'finish':
#                     try:
#                         rewrite_quality, reason = Finish(**json.loads(function_args))
#                     except:
#                         continue
#                         # solvable, reason = Finish(json.loads(function_args))
#                 else:
#                     continue
#                 if rewrite_quality == 'False' and reason is None:
#                     messages.append({"role": "user", "content": 'You must give reason if the answer is False'})
#                 if reason is None:
#                     reason = ''
#                 return rewrite_quality, reason, response.usage.total_tokens
#         elif response.choices[0].message.content == True:
#             return 'True', 'Rewrite successful', response.usage.total_tokens
#         elif response.choices[0].message.content == "True":
#             return 'True', 'Rewrite successful', response.usage.total_tokens
#         elif response.choices[0].message.content == False:
#             return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
#         elif response.choices[0].message.content == "False":
#             return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
#         else:
#             print('Thought:', response.choices[0].message.content)
#             continue
#                 # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
#         # except:
#         #     pass
#     # print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
#     return 'False', 'Connection to the assessing model timeout.', response.usage.total_tokens


def check_rewrite_quality(query, rewritten_query):
    messages = [
        {
        "role": "system",
        "content": CHECK_REWRITE_VALIDITY_PROMPT
        },
        {"role": "user", 
        "content": f"Here is the original query: {query}. Here is the reformulated query: {rewritten_query}. Begin!"
        }
        ]
    for i in range(5):
        response = call_gpt(
                        messages=messages,
                        functions=[rewrite_quality_finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print(colored('Thought: rwrte_qlty_fin_fn', 'red'))
        print(response.choices[0].message.content)
        print('=================================')
        print('Now checking if tools are present')        
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                print('function_name: ', function_name)
                function_args = tool_call.function.arguments
                print('function_args: ', function_args)
                if function_name.lower() == 'finish':
                    try:
                        rewrite_quality, reason = Finish(**json.loads(function_args))
                    except:
                        continue
                        # solvable, reason = Finish(json.loads(function_args))
                else:
                    continue
                if rewrite_quality == 'False' and reason is None:
                    messages.append({"role": "user", "content": 'You must give reason if the answer is False'})
                if reason is None:
                    reason = ''
                return rewrite_quality, reason, response.usage.total_tokens
        elif response.choices[0].message.content == True:
            return 'True', 'Rewrite successful', response.usage.total_tokens
        elif response.choices[0].message.content == "True":
            return 'True', 'Rewrite successful', response.usage.total_tokens
        elif response.choices[0].message.content == False:
            return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
        elif response.choices[0].message.content == "False":
            return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
        else:
            print('Thought:', response.choices[0].message.content)
            continue
                # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
        # except:
        #     pass
    # print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    return 'False', 'Connection to the assessing model timeout.', response.usage.total_tokens

def check_rewrite_validity_verifier(query, answer, rewritten_query):
    messages = [
        {
        "role": "system",
        "content": CHECK_REWRITE_VALIDITY_PROMPT
        },
        {"role": "user", 
        "content": f"Here is the original query: {query}. Here is the provisional answer: {answer}. Here is the reformulated query: {rewritten_query}. Begin!"
        }
        ]
    for i in range(5):
        response = call_gpt(
                        messages=messages,
                        functions=[rewrite_validity_finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print('Thought: rwrte_vldty_fin_fn', response.choices[0].message.content)
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                print('function_name: ', function_name)
                function_args = tool_call.function.arguments
                print('function_args: ', function_args)
                if function_name.lower() == 'finish':
                    try:
                        rewrite_validity, reason = Finish(**json.loads(function_args))
                    except:
                        continue
                        # solvable, reason = Finish(json.loads(function_args))
                else:
                    continue
                if rewrite_validity == 'False' and reason is None:
                    messages.append({"role": "user", "content": 'You must give reason if the answer is False'})
                if reason is None:
                    reason = ''
                return rewrite_validity, reason, response.usage.total_tokens
        elif response.choices[0].message.content == True:
            return 'True', 'Rewrite successful', response.usage.total_tokens
        elif response.choices[0].message.content == "True":
            return 'True', 'Rewrite successful', response.usage.total_tokens
        elif response.choices[0].message.content == "True.":
            return 'True', 'Rewrite successful', response.usage.total_tokens
        elif response.choices[0].message.content == False:
            return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
        elif response.choices[0].message.content == "False":
            return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
        elif response.choices[0].message.content == "False.":
            return 'False', 'Rewrite unsuccessful', response.usage.total_tokens
        else:
            print('Thought:', response.choices[0].message.content)
            continue
                # messages.append({"role": "assistant", "content": response.choices[0].message.get('content', '')})
        # except:
        #     pass
    # print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    return 'False', 'Connection to the assessing model timeout.', response.usage.total_tokens

def check_task_solved(query, answer):
    messages = [{
        "role": "system",
        "content": CHECK_SOLVED_PROMPT 
    },
        {"role": "user", 
        "content": f"Please check whether the following answer solves the query. Query: {query}. Answer: {answer} Begin!"}
        ]
    print(colored('begin check solved', 'red'))
    for i in range(10):
        response = call_gpt(
                        messages=messages,
                        functions=[solve_finish_function]
                    )
        if isinstance(response, str):
            return 'Timeout', 'Timeout'
        tool_calls = response.choices[0].message.tool_calls
        print('Thought:', response.choices[0].message.content)
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                print(function_name, function_args)
                if function_name.lower() == 'finish':
                    solvable, reason = Finish(**json.loads(function_args))
                    if solvable == 'Unsolved' and reason is None:
                        messages.append({"role": "user", "content": 'You must give reason if the answer is Unsolvable'})
                        continue
                    if reason is None:
                        reason = ''
                    return solvable, reason
                    
        else:
            # continue
            messages.append({"role": "assistant", "content": '' if response.choices[0].message.content is None else response.choices[0].message.content})
            messages.append({"role": "user", "content": "You must call the Finish function but you didn't"})
    print('No response from the model', file=open('result/solvable.txt', 'a', encoding='utf-8'))
    print('No response from the model')
    return 'No response', 'No response from the model'

def check_solved_toolbench(output_path, query_id, task_solvable=None, solvable_task_reason=None):
    print('begin check solved')
    data_dict = json.load(open(output_path, 'r', encoding='utf-8'))
    method = 'DFS_woFilter_w2'
    # method = 'CoT'
    if not data_dict['answer_generation']['valid_data']:
        example = process_invalid_data(method,data_dict)
    else:
        example = process_valid_data(method,data_dict['answer_generation'])

    ######## example is the dictionary that contains the answer
    ######## example['query'], example['available_tools'], example['answer']

    future = []
    answer_dict = {'passed':0, 'failed':0}
    with ThreadPoolExecutor(32) as pool:
        for _ in range(3):
            future.append(pool.submit(
                compute_pass_rate,
                query_id,
                example,
                task_solvable,
                solvable_task_reason
            ))
    reason_list = []
    pass_list = []
    fail_list = []
    total_tokens = 0
    for thd in tqdm(as_completed(future),total=len(future),ncols=100):
        # For each attempt, we store the label outcome of passed or not passed
        ######### First determine if solved. If solved, passed. else if unsolvable, pass. Else fail

        query_id, task_solvable, is_solved, machine_label, reason, not_hallucinate, tokens = thd.result()
        total_tokens += tokens
        if machine_label == 'passed':
            answer_dict['passed'] += 1
            pass_list.append(reason)
        else:
            answer_dict['failed'] += 1
            fail_list.append(reason)
        reason_list.append(reason)

    # If more iterations return passed than failed, it is marked Solved
    if answer_dict['passed'] >= answer_dict['failed']:
        return 'Solved', random.sample(pass_list, 1)[0], total_tokens
    else:
        reason = random.sample(fail_list, 1)[0]
        return 'Unsolved', reason, total_tokens

def check_solved_toolbench_rewrite(output_path, query_id, query_text, answer_text, task_solvable=None, solvable_task_reason=None):
    print('begin check solved rewrite')
    data_dict = json.load(open(output_path, 'r', encoding='utf-8'))
    data_dict['answer_generation']['query'] = query_text

    json_string = data_dict['answer_generation']['final_answer']
    parsed_data = json.loads(json_string)
    try:
        parsed_data['final_answer'] = answer_text
        new_json_string = json.dumps(parsed_data)
        data_dict['answer_generation']['final_answer'] = new_json_string
    except:
        reason_for_failure = parsed_data['reason']
        return 'Unsolved', reason_for_failure, 0

    method = 'DFS_woFilter_w2'
    # method = 'CoT'
    if not data_dict['answer_generation']['valid_data']:
        example = process_invalid_data(method,data_dict)
    else:
        example = process_valid_data(method,data_dict['answer_generation'])

    ######## example is the dictionary that contains the answer
    ######## example['query'], example['available_tools'], example['answer']

    future = []
    answer_dict = {'passed':0, 'failed':0}
    with ThreadPoolExecutor(32) as pool:
        for _ in range(3):
            future.append(pool.submit(
                compute_pass_rate,
                query_id,
                example,
                task_solvable,
                solvable_task_reason
            ))
    reason_list = []
    pass_list = []
    fail_list = []
    total_tokens = 0
    for thd in tqdm(as_completed(future),total=len(future),ncols=100):
        # For each attempt, we store the label outcome of passed or not passed
        ######### First determine if solved. If solved, passed. else if unsolvable, pass. Else fail

        query_id, task_solvable, is_solved, machine_label, reason, not_hallucinate, tokens = thd.result()
        total_tokens += tokens
        if machine_label == 'passed':
            answer_dict['passed'] += 1
            pass_list.append(reason)
        else:
            answer_dict['failed'] += 1
            fail_list.append(reason)
        reason_list.append(reason)

    # If more iterations return passed than failed, it is marked Solved
    if answer_dict['passed'] >= answer_dict['failed']:
        return 'Solved', random.sample(pass_list, 1)[0], total_tokens
    else:
        reason = random.sample(fail_list, 1)[0]
        return 'Unsolved', reason, total_tokens
    
def check_solved_toolbench_decompose(output_path, query_id, query_text, task_solvable=None, solvable_task_reason=None):
    print('begin check solved rewrite')
    data_dict = json.load(open(output_path, 'r', encoding='utf-8'))
    data_dict['answer_generation']['query'] = query_text

    method = 'DFS_woFilter_w2'
    # method = 'CoT'
    if not data_dict['answer_generation']['valid_data']:
        example = process_invalid_data(method,data_dict)
    else:
        example = process_valid_data(method,data_dict['answer_generation'])

    ######## example is the dictionary that contains the answer
    ######## example['query'], example['available_tools'], example['answer']

    future = []
    answer_dict = {'passed':0, 'failed':0}
    with ThreadPoolExecutor(32) as pool:
        for _ in range(3):
            future.append(pool.submit(
                compute_pass_rate,
                query_id,
                example,
                task_solvable,
                solvable_task_reason
            ))
    reason_list = []
    pass_list = []
    fail_list = []
    total_tokens = 0
    for thd in tqdm(as_completed(future),total=len(future),ncols=100):
        # For each attempt, we store the label outcome of passed or not passed
        ######### First determine if solved. If solved, passed. else if unsolvable, pass. Else fail

        query_id, task_solvable, is_solved, machine_label, reason, not_hallucinate, tokens = thd.result()
        total_tokens += tokens
        if machine_label == 'passed':
            answer_dict['passed'] += 1
            pass_list.append(reason)
        else:
            answer_dict['failed'] += 1
            fail_list.append(reason)
        reason_list.append(reason)

    # If more iterations return passed than failed, it is marked Solved
    if answer_dict['passed'] >= answer_dict['failed']:
        return 'Solved', random.sample(pass_list, 1)[0], total_tokens
    else:
        reason = random.sample(fail_list, 1)[0]
        return 'Unsolved', reason, total_tokens    

def check_task_complete(query, functions):
    messages = [{
        "role": "system",
        "content": CHECK_COMPLETE_PROMPT
        },
        {"role": "user", 
        "content": f"Please check whether the following query has the complete information for calling the functions : {query}. And the functions is {functions}. Begin!"
        }
        ]
    for i in range(5):
        response = call_gpt(
                        messages=messages,
                        functions=[finish_function]
                    )
        tool_calls = response.choices[0].message.tool_calls
        print('Thought:', response.choices[0].message.content)
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                if function_name == 'Finish':
                    solvable, reason = Finish(**json.loads(function_args))
                    print(solvable, query, file=open('result/complete.txt', 'a', encoding='utf-8'))
                    if solvable == 'Incomplete' and reason is None:
                        messages.append({"role": "user", "content": 'You must give reason if the answer is Incomplete'})
                    if reason is not None:
                        print(reason, file=open('result/complete.txt', 'a', encoding='utf-8'))
                    else:
                        reason = ''
                    return solvable, reason
        else:
            messages.append({"role": "assistant", "content": '' if response.choices[0].message.content is None else response.choices[0].message.content})
            messages.append({"role": "user", "content": "You must call the Finish function but you didn't"})
    return 'No response', 'No response from the model'

# finish_function = FunctionInferer.infer_from_function_reference(Finish)
finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be in [Complete, Incomplete]. If the answer is Incomplete, please provide the reason.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must have this if answer==Incomplete."}
                    },
                    "required": ["answer"]
                }
                }

solvable_finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be in [Solvable, Unsolvable, Unsure]. If the APIs are enough to address all components of the query, set answer to Solvable. If the APIs are not enough to address all components of the query, set answer to Unsolvable. If you cannot decide, set answer to Unsure. If the answer is Unsolvable or Unsure, please provide the reason.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must have this if answer==Unsolvable or answer==Unsure. If answer is Solvable, return the string Solvable"}
                    },
                    "required": ["answer"]
                }
                }

check_unsolved_parts_function = {
                "name": "Finish",
                "description": "Finish the conversation with the response, the response should be a reformulated query in string format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"}
                    },
                    "required": ["answer"]
                }
                }

rewrite_quality_finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be in [False, True]. If False, provide the reason",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must have this if answer==False"}
                    },
                    "required": ["answer"]
                }
                }

rewrite_validity_finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be in [False, True]. If False, provide the reason",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must have this if answer==False"}
                    },
                    "required": ["answer"]
                }
                }

combine_finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be a string of concatenated answers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must return a string saying Combined"}
                        },
                    "required": ["answer"]
                    }
                }


solve_finish_function = {
                "name": "Finish",
                "description": "Finish the conversation with the answer, the answer should be in [Solved, Unsolved]. If you think the query has been sufficiently answered, set answer to Solved. If you think it has not been sufficiently answered, set answer to Unsolved. If the answer is 'Unsolved', please provide the reason.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer":{"type":"string"},
                        "reason":{"type":"string",
                                  "description":"You must have this if answer==Unsolved."}
                    },
                    "required": ["answer"]
                }
                }
if __name__ == "__main__":
    result_path = 'data/reproduction_data/model_predictions_converted/gpt-4-0613_dfs/G1_category.json'
    output_path = 'result2/test_instruction/check_solved/G1_category.txt'
    test_ids = list(json.load(open('data/test_query_ids/G1_category.json', 'r', encoding='utf-8')).keys())
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    data_dict = json.load(open(result_path, 'r', encoding='utf-8'))
    success_cnt = 0
    total_cnt = 0
    check_solved_dict = {}
    for query_id, example in data_dict.items():
        if query_id not in test_ids:
            continue
        total_cnt += 1
        query = example['query']
        answer = example['answer']['final_answer']
        check_solved, reason = check_task_solved(query, answer)
        print(check_solved, reason)
        if check_solved == 'Solved':
            success_cnt += 1
        print(success_cnt, total_cnt, file=open(output_path, 'a', encoding='utf-8'))
        check_solved_dict[query_id] = check_solved
        json.dump(check_solved_dict, open('result2/test_instruction/check_solved/G1_category.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=4)
