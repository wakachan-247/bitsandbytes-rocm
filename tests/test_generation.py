import pytest
import torch
import math

from itertools import product

import transformers
from transformers import (
  AutoConfig,
  AutoModelForCausalLM,
  AutoTokenizer,
  BitsAndBytesConfig,
  GenerationConfig,
  set_seed,

)



def get_4bit_config():
  return BitsAndBytesConfig(
    load_in_4bit=True,
    load_in_8bit=False,
    llm_int8_threshold=6.0,
    llm_int8_has_fp16_weight=False,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type='nf4',
  )


def get_model_and_tokenizer(config):
    model_name_or_path, quant_type = config
    bnb_config = get_4bit_config()
    if quant_type == '16bit':
        bnb_config.load_in_4bit = False
    else:
        bnb_config.bnb_4bit_quant_type= quant_type
    model = AutoModelForCausalLM.from_pretrained(model_name_or_path,
        quantization_config=bnb_config,
        max_memory={0:'48GB'},
        device_map='auto',
        torch_dtype=torch.bfloat16
        ).eval()

    tokenizer = transformers.AutoTokenizer.from_pretrained(model_name_or_path)

    return model, tokenizer

def get_prompt_for_generation_eval(text, add_roles=True):
    description = (
        "A chat between a curious human and an artificial intelligence assistant. "
        "The assistant gives helpful, detailed, and polite answers to the user's questions."
    )
    if add_roles:
        prompt = f'{description} ### Human: {text} ### Assistant:'
    else:
        prompt = f'{description} {text}'
    return prompt

def generate(model, tokenizer, text, generation_config, prompt_func=get_prompt_for_generation_eval):
    text = prompt_func(text)
    inputs = tokenizer(text, return_tensors="pt").to('cuda:0')
    outputs = model.generate(inputs=inputs['input_ids'], generation_config=generation_config)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

models = ['huggyllama/llama-7b', 'bigscience/bloom-1b7']
dtypes = ['nf4', 'fp4', '16bit']
load_in_4bit = [True, False]
values = list(product(models, dtypes))
strfunc = lambda lst: [str(x) for x in lst]
ids = ['_'.join(strfunc(x)) for x in values]
@pytest.fixture(scope='session', params=values, ids=ids)
def model_and_tokenizer(request):
    model, tokenizer = get_model_and_tokenizer(request.param)
    yield model, tokenizer
    del model

@pytest.mark.parametrize("inference_kernel", [True, False], ids=['inference_kernel_True', 'inference_kernel_False'])
@pytest.mark.parametrize("dtype", [torch.float16, torch.bfloat16, torch.float32], ids=['fp16', 'bf16', 'fp32'])
def test_pi(model_and_tokenizer, dtype, inference_kernel):

    model, tokenizer = model_and_tokenizer

    generation_config = transformers.GenerationConfig(
        max_new_tokens=20,
        do_sample=True,
        top_p=0.9,
        temperature=0.7,
    )
    generation_config.max_new_tokens = 20


    #text = 'Please write down the first 50 digits of pi.'
    #text = get_prompt_for_generation_eval(text)
    #text += ' Sure, here the first 50 digits of pi: 3.14159'
    n_cases = 3
    text = '3.14159'
    if hasattr(model.config, 'quantization_config'):
        model.config.quantization_config.bnb_4bit_compute_dtype = dtype

    if not inference_kernel:
        text = [text]*n_cases
    inputs = tokenizer(text, return_tensors="pt").to('cuda:0')
    x = inputs['input_ids']
    failure_count = 0
    outputs = []
    if inference_kernel:
        for i in range(n_cases):
            output = model.generate(x, generation_config=generation_config)
            textout = tokenizer.decode(output[0], skip_special_tokens=True)
            outputs.append(textout)
    else:
        outputs = model.generate(x, generation_config=generation_config)
        outputs = [tokenizer.decode(output, skip_special_tokens=True) for output in outputs]


    assert len(outputs) == n_cases
    for i in range(n_cases):
        if not outputs[i][:len(str(math.pi))] == str(math.pi):
            failure_count += 1
    if failure_count > 1:
        print(math.pi)
        for out in outputs:
            print(out)
        raise ValueError(f'Failure count: {failure_count}/{n_cases}')


