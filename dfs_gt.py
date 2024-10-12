#encoding:utf-8
import os
from typing import List, Dict, Any
import re
from tqdm import tqdm
import time
from termcolor import colored
from copy import deepcopy
from anytool.api_database_function import *
from anytool.verifier import check_solved_toolbench
import os
from anytool.rapidapi import pipeline_runner
import json
from config_example import *

class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
# For pipeline environment preparation
def get_white_list(tool_root_dir):
    print('Getting white list')
    # white_list_dir = os.path.join(tool_root_dir)
    white_list = {}
    for cate in tqdm(os.listdir(tool_root_dir)):
        if not os.path.isdir(os.path.join(tool_root_dir,cate)):
            continue
        for file in os.listdir(os.path.join(tool_root_dir,cate)):
            if not file.endswith(".json"):
                continue
            
            standard_tool_name = file.split(".")[0]
            with open(os.path.join(tool_root_dir,cate,file)) as reader:
                js_data = json.load(reader)
            # print(js_data)
            try:
                origin_tool_name = js_data["tool_name"]
            except:
                print('#'*100)
                print('error:', 'js_data', js_data[0])
            
            white_list[standardize(origin_tool_name)] = {"description": js_data["tool_description"], "standard_tool_name": standard_tool_name}
    return white_list

def standardize(string):
    if not isinstance(string, str):
        print('*'*100)
        print(string)
    res = re.compile("[^\\u4e00-\\u9fa5^a-z^A-Z^0-9^_]")
    string = res.sub("_", string)
    string = re.sub(r"(_)\1+","_", string).lower()
    while True:
        if len(string) == 0:
            return string
        if string[0] == "_":
            string = string[1:]
        else:
            break
    while True:
        if len(string) == 0:
            return string
        if string[-1] == "_":
            string = string[:-1]
        else:
            break
    if string[0].isdigit():
        string = "get_" + string
    return string

tool_root_dir = extracted_folder_path_for_agg

print('Loading white list')
white_list = get_white_list(tool_root_dir)
def contain(candidate_list, white_list):
    output = []
    for cand in candidate_list:
        if cand not in white_list.keys():
            print(f"Candidate {cand} NOT in white list")
            return False
        # print(white_list[cand])
        output.append(white_list[cand])
    return output
def change_name(name):
    change_list = ["from", "class", "return", "false", "true", "id", "and"]
    if name in change_list:
        name = "is_" + name
    return name

def solve_given_api_main(query, api_list, i, white_list, messages=None):
    print('Inside Solver')
    print(f'Query: {query}')
    answer_dir = dfs_args.output_answer_file
    print(f'Answer dir: {answer_dir}')
    if not os.path.exists(answer_dir):
        os.mkdir(answer_dir)
    if os.path.exists(os.path.join(answer_dir, f'{i}_DFS_woFilter_w2.json')):
        os.remove(os.path.join(answer_dir, f'{i}_DFS_woFilter_w2.json'))
    
    method = dfs_args.method
    backbone_model = dfs_runner.backbone_model
    data_dict = {}
    result_data = {}
    data_dict['query'] = query
    data_dict['api_list'] = api_list
    print("Starting standardize")
    origin_tool_names = [standardize(cont["tool_name"]) for cont in api_list]
    print("Done standardize")
    print(origin_tool_names)
    print("Starting contain")
    tool_des = contain(origin_tool_names,white_list)
    print("Done contain")
    print('Messages sent to method_converter')
    print(messages)

    if tool_des == False:
        result_data = {'result': 'no tool description'}
        return False, result_data
    tool_des = [[cont["standard_tool_name"], cont["description"]] for cont in tool_des]
    task = (method, backbone_model, i, data_dict, dfs_args, answer_dir, tool_des)
    for _ in range(3):
        ### Found in rapidapi.py
        print("Reached dfs_run")
        dfs_runner.run(task, messages)
        print("Finished dfs_run")
        ### This is when the return is an integer 1 and the json with answer is created and saved
        ### Generated during the run, then run_single_task (saved here), then method_converter, then DFS class

        result = json.load(open(os.path.join(answer_dir, f'{i}_DFS_woFilter_w2.json'), 'r', encoding='utf-8'))
        ### This loads the solution path 
        ### Generated during the run, then run_single_task (saved here), then method_converter, then DFS class
        try:
            result_data['result'] = json.loads(result['answer_generation']['final_answer'])
            print("Result Data TRY Confirmed")
        except:
            print(result['answer_generation']['final_answer'])
            final_answer_str = result['answer_generation']['final_answer']
            return_type = final_answer_str[final_answer_str.find('"return_type": "')+len('"return_type": "'):final_answer_str.find('",')]
            result_data['result'] = {
                "return_type": return_type,
            }
            if '"final_answer": "' in final_answer_str:
                final_answer = final_answer_str[final_answer_str.find('"final_answer": "')+len('"final_answer": "'):]
                result_data['result']['final_answer'] = final_answer
            elif return_type == 'give_answer':
                continue
            if '"reason": "' in final_answer_str:
                reason = final_answer_str[final_answer_str.find('"reason": "')+len('"reason": "'):]
                result_data['result']['reason'] = reason
            result['answer_generation']['final_answer'] = json.dumps(result_data['result'])
        if result['answer_generation']['finish_type'] == 'give_answer' and 'final_answer' in result_data['result'] and  result_data['result']['final_answer'] != '':
            solved = True
        else:
            solved = False
        
        print("Returning solve_data")
        print(result_data)
        return solved, result_data
    result_data['result']['final_answer'] = ''
    return False, result_data
      
# def api_collector(query, api_list, white_list, messages=None):
#     method = dfs_args.method
#     backbone_model = dfs_runner.backbone_model
#     data_dict = {}
#     result_data = {}
#     data_dict['query'] = query
#     data_dict['api_list'] = api_list
#     print("Starting standardize")
#     origin_tool_names = [standardize(cont["tool_name"]) for cont in api_list]
#     print("Done standardize")
#     print(origin_tool_names)
#     print("Starting contain")
#     tool_des = contain(origin_tool_names, white_list)
#     print("Done contain")
#     print('Messages sent to method_converter')
#     print(messages)

#     if tool_des == False:
#         result_data = {'result': 'no tool description'}
#         return False, result_data
#     tool_des = [[cont["standard_tool_name"], cont["description"]] for cont in tool_des]
#     task = (method, backbone_model, i, data_dict, dfs_args, answer_dir, tool_des)
#     for _ in range(3):
#         ### Found in rapidapi.py
#         print("Reached dfs_run")
#         dfs_runner.run(task, messages)
#         print("Finished dfs_run")
#         ### This is when the return is an integer 1 and the json with answer is created and saved
#         ### Generated during the run, then run_single_task (saved here), then method_converter, then DFS class

#         result = json.load(open(os.path.join(answer_dir, f'{i}_DFS_woFilter_w2.json'), 'r', encoding='utf-8'))
#         ### This loads the solution path 
#         ### Generated during the run, then run_single_task (saved here), then method_converter, then DFS class
#         try:
#             result_data['result'] = json.loads(result['answer_generation']['final_answer'])
#             print("Result Data TRY Confirmed")
#         except:
#             print(result['answer_generation']['final_answer'])
#             final_answer_str = result['answer_generation']['final_answer']
#             return_type = final_answer_str[final_answer_str.find('"return_type": "')+len('"return_type": "'):final_answer_str.find('",')]
#             result_data['result'] = {
#                 "return_type": return_type,
#             }
#             if '"final_answer": "' in final_answer_str:
#                 final_answer = final_answer_str[final_answer_str.find('"final_answer": "')+len('"final_answer": "'):]
#                 result_data['result']['final_answer'] = final_answer
#             elif return_type == 'give_answer':
#                 continue
#             if '"reason": "' in final_answer_str:
#                 reason = final_answer_str[final_answer_str.find('"reason": "')+len('"reason": "'):]
#                 result_data['result']['reason'] = reason
#             result['answer_generation']['final_answer'] = json.dumps(result_data['result'])
#         if result['answer_generation']['finish_type'] == 'give_answer' and 'final_answer' in result_data['result'] and  result_data['result']['final_answer'] != '':
#             solved = True
#         else:
#             solved = False
        
#         print("Returning solve_data")
#         print(result_data)
#         return solved, result_data
#     result_data['result']['final_answer'] = ''
#     return False, result_data






from arguments import parse_args
args = parse_args()
output_path = args.output_dir

os.makedirs(output_path, exist_ok=True)

op_key = os.environ.get('OPENAI_API_KEY', None)

# dfs_args = dotdict(dict(backbone_model=backbone, openai_key=op_key, model_path='your_model_path/', tool_root_dir='/Users/yashthirani/Desktop/ClonedRepos/ToolLLM/ToolBench/data/toolenv/tools', lora=False, lora_path='your_lora_path if lora', max_observation_length=1024, max_source_sequence_length=4096, max_sequence_length=8192, observ_compress_method='truncate', method='DFS_woFilter_w2', input_query_file='data/test_instruction/G1_tool.json', output_answer_file=output_path, toolbench_key=toolbench_key, rapidapi_key='', use_rapidapi_key=False, api_customization=False))
dfs_args = dotdict(dict(backbone_model=backbone, openai_key=op_key, model_path='your_model_path/', tool_root_dir=extracted_folder_path_for_agg, lora=False, lora_path='your_lora_path if lora', max_observation_length = obs_length, max_source_sequence_length=4096, max_sequence_length=8192, observ_compress_method='truncate', method=parse_method, input_query_file='data/test_instruction/G1_tool.json', output_answer_file=output_path, toolbench_key=toolbench_key, rapidapi_key='', use_rapidapi_key=False, api_customization=False))
print("Reached dfs_args")

dfs_runner = pipeline_runner(dfs_args)

if __name__ == '__main__':
    retrieved_api_nums = 10
    query_list = []
    cnt = 0
    success = 0
    no_return_type_cnt = 0
    failed = []
    task_solvable = 'Solvable'
    solvable_reason = 'Solvable checked by human'
    # for root, dirs, files in os.walk('result/generated_solve_given_api_solvable2'):
    solved_dict = json.load(open('solved_dict.json', 'r', encoding='utf-8'))
    for i in range(262):
        t_s = time.time()
        comparison_data = {}
        data_load = json.load(open(f'{args.query_dir}/{i}.json', 'r', encoding='utf-8'))
        if str(data_load['query_id']) in solved_dict and solved_dict[str(data_load['query_id'])]['solved'] != 'Solved':
            continue
        
        query = data_load['query']
        # continue
        cnt += 1
        if os.path.exists(os.path.join(output_path, f'{i}_DFS_woFilter_w2.json')):
            data = json.load(open(os.path.join(output_path, f'{i}_DFS_woFilter_w2.json'), 'r', encoding='utf-8'))
            final_data = json.load(open(os.path.join(output_path, f'{i}.json'), 'r', encoding='utf-8'))
            if data['answer_generation']['finish_type'] != 'give_answer':
                print(i)
            if 'final_answer' in data['answer_generation'] and not any(word in data['answer_generation']['final_answer'].lower() for word in exclusion_words):
                if 'check_solved' in final_data:
                    check_solved = final_data['check_solved']
                    reason = final_data['reason']
                else:
                    check_solved, reason = check_solved_toolbench(f'{output_dir}/{i}_DFS_woFilter_w2.json', i, data_load['query_id'], task_solvable, solvable_reason)
                if check_solved == 'Solved':
                    success += 1
                else:
                    check_solved = 'Unsolved'
            else:
                check_solved = 'Unsolved'
                print(output_path, i, file=open(os.path.join(output_path, 'failed.txt'), 'a'))
            print(success, cnt, i+1, file=open(os.path.join(output_path, 'success_cnt.txt'), 'a'))
            continue
        find_api_messages_to_save = []
        messages_to_save = []
        try:
            gt_api_list = [{'category_name': api.get('category_name', ''), 'tool_name':api.get('tool_name', ''),'api_name':api.get('api_name', '') }for api in data_load['api_list'][-1]]
            # gt_api_list = [{'category_name': api.get('category_name', ''), 'tool_name':api.get('tool_name', ''),'api_name':api.get('api_name', '') }for api in data_load['gt_api_list']]
            comparison_data['gt_api_list'] = gt_api_list
        except:
            pass
        print('#'*100, file=open(os.path.join(output_path, 'time.txt'), 'a'))
        solved, result_data = solve_given_api_main(query, data_load['gt_api_list'], i)
        if solved:
            check_solved, reason, _ = check_solved_toolbench(f'{output_dir}/{i}_DFS_woFilter_w2.json', i, data_load['query_id'], task_solvable, solvable_reason)
            if check_solved == 'Solved':
                success += 1
        else:
            check_solved = 'Unsolved'
            reason = ''
            print(output_path, i, file=open(os.path.join(output_path, 'failed.txt'),'a'))
        print(success, cnt, i+1, file=open(os.path.join(output_path, 'success_cnt.txt'), 'a'))
        final_data = {}
        final_data['query_id'] = data_load['query_id']
        final_data['query'] = data_load['query']
        final_data['gt_api_list'] = data_load['gt_api_list']
        final_data['gt_answer'] = data_load['final_answer']
        final_data['result'] = result_data
        final_data['check_solved'] = check_solved
        final_data['reason'] = reason
        json.dump(final_data, open(os.path.join(output_path, f'{i}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=4)

        print(f'time: {time.time()-t_s}', file=open(os.path.join(output_path, 'time.txt'),'a'))
      
