# Copyright 2023-present the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import warnings
from typing import Any, List, Optional

import torch
from torch import nn

from peft.tuners.lora import LoraLayer
from peft.tuners.tuners_utils import check_adapters_to_merge
from peft.utils import transpose


class AdaLoraLayer(LoraLayer):
    # List all names of layers that may contain adapter weights
    # Note: ranknum doesn't need to be included as it is not an nn.Module
    adapter_layer_names = ("lora_A", "lora_B", "lora_E", "lora_embedding_A", "lora_embedding_B")
    # other_param_names is defined in LoraLayer

    def __init__(self, base_layer: nn.Module) -> None:
        super().__init__(base_layer)
        self.lora_E = nn.ParameterDict({})
        self.lora_A = nn.ParameterDict({})
        self.lora_B = nn.ParameterDict({})
        self.ranknum = nn.ParameterDict({})

    def update_layer(self, adapter_name, r, lora_alpha, lora_dropout, init_lora_weights, **kwargs):
        if r <= 0:
            raise ValueError(f"`r` should be a positive integer value but the value passed is {r}")

        self.r[adapter_name] = r
        self.lora_alpha[adapter_name] = lora_alpha
        if lora_dropout > 0.0:
            lora_dropout_layer = nn.Dropout(p=lora_dropout)
        else:
            lora_dropout_layer = nn.Identity()

        indices = kwargs.pop('indices')
        layer_idx = kwargs.pop('layer_idx')
        target_name = kwargs.pop('target_name')
        current_key = kwargs.pop('current_key')
        self.target_name = target_name
        print(current_key)

        self.lora_dropout[adapter_name] = lora_dropout_layer
        if indices is None:
            # Actual trainable parameters
            # Right singular vectors
            self.lora_A[adapter_name] = nn.Parameter(torch.randn(r, self.in_features))
            # Left singular vectors
            self.lora_B[adapter_name] = nn.Parameter(torch.randn(self.out_features, r))
        else:
            # if target_name=='fc1':
            #     # row_indices = indices[f'visual.transformer.resblocks.{layer_idx}.mlp.c_fc'][0]
            #     # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.mlp.c_fc'][1]

            #     row_indices = indices[f'{layer_idx}.fc1'][0]
            #     col_indices = indices[f'{layer_idx}.fc1'][1]
            # elif target_name=='fc2':
            #     # row_indices = indices[f'visual.transformer.resblocks.{layer_idx}.mlp.c_proj'][0]
            #     # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.mlp.c_proj'][1]
            #     row_indices = indices[f'{layer_idx}.fc2'][0]
            #     col_indices = indices[f'{layer_idx}.fc2'][1]
            # elif target_name in ['q_proj', 'k_proj', 'v_proj']:
            #     if target_name=='q_proj':                    
            #         # row_idxs = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][0]
            #         # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][1]
            #         row_idxs = indices[f'{layer_idx}.attn_in'][0]
            #         col_indices = indices[f'{layer_idx}.attn_in'][1]
            #         row_idxs = [idx for idx in row_idxs if idx<768]
            #         row_indices = row_idxs
            #     elif target_name=='k_proj':
            #         # row_idxs = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][0]
            #         # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][1]
            #         row_idxs = indices[f'{layer_idx}.attn_in'][0]
            #         col_indices = indices[f'{layer_idx}.attn_in'][1]
            #         row_idxs = [idx-768 for idx in row_idxs if idx>=768 and idx<1536]
            #         row_indices = row_idxs
            #     elif target_name=='v_proj':
            #         # row_idxs = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][0]
            #         # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.attn'][1]
            #         row_idxs = indices[f'{layer_idx}.attn_in'][0]
            #         col_indices = indices[f'{layer_idx}.attn_in'][1]
            #         row_idxs = [idx-768*2 for idx in row_idxs if idx>=1536]
            #         row_indices = row_idxs
            # elif target_name=='out_proj':
            #     # row_indices = indices[f'visual.transformer.resblocks.{layer_idx}.attn.out_proj'][0]
            #     # col_indices = indices[f'visual.transformer.resblocks.{layer_idx}.attn.out_proj'][1]
            #     row_indices = indices[f'{layer_idx}.attn_out'][0]
            #     col_indices = indices[f'{layer_idx}.attn_out'][1]

            if 'intermediate.dense' in current_key:
                row_indices = indices[f'{layer_idx}.fc1'][0]
                col_indices = indices[f'{layer_idx}.fc1'][1]
            elif 'output.dense' in current_key and 'attention' not in current_key:
                row_indices = indices[f'{layer_idx}.fc2'][0]
                col_indices = indices[f'{layer_idx}.fc2'][1]
            elif 'self.query_proj' in current_key:
                row_indices = indices[f'{layer_idx}.attn_in'][0]
                col_indices = indices[f'{layer_idx}.attn_in'][1]
            elif 'key_proj' in current_key:
                row_indices = indices[f'{layer_idx}.attn_in'][0]
                col_indices = indices[f'{layer_idx}.attn_in'][1]
            elif 'value_proj' in current_key:                    
                row_indices = indices[f'{layer_idx}.attn_in'][0]
                col_indices = indices[f'{layer_idx}.attn_in'][1]
            elif 'attention.output.dense' in current_key:
                row_indices = indices[f'{layer_idx}.attn_out'][0]
                col_indices = indices[f'{layer_idx}.attn_out'][1]

            self.indices_m = torch.tensor(row_indices).cuda().long()
            self.indices_n = torch.tensor(col_indices).cuda().long()
            self.indices_m = torch.unique(self.indices_m)
            self.indices_n = torch.unique(self.indices_n)
            self.indices_mn = torch.cartesian_prod(self.indices_m, self.indices_n)
            
            indices_m = torch.tensor(row_indices)
            indices_n = torch.tensor(col_indices)
            indices_m = torch.unique(indices_m)
            indices_n = torch.unique(indices_n)
            fan_out = len(indices_m)
            fan_in = len(indices_n)
            # Actual trainable parameters
            # Right singular vectors
            self.lora_A[adapter_name] = nn.Parameter(torch.randn(r, fan_out))
            # Left singular vectors
            self.lora_B[adapter_name] = nn.Parameter(torch.randn(fan_in, r))
            print(target_name, [r, fan_out], [fan_in, r])

        # Singular values
        self.lora_E[adapter_name] = nn.Parameter(torch.randn(r, 1))
        # The current rank
        self.ranknum[adapter_name] = nn.Parameter(torch.randn(1), requires_grad=False)
        self.ranknum[adapter_name].data.fill_(float(r))
        self.ranknum[adapter_name].requires_grad = False
        self.scaling[adapter_name] = lora_alpha if lora_alpha > 0 else float(r)
        if init_lora_weights:
            self.reset_lora_parameters(adapter_name)

        if hasattr(self.get_base_layer(), "qweight"):
            # QuantLinear
            self.to(self.get_base_layer().qweight.device)
        else:
            self.to(self.get_base_layer().weight.device)
        self.set_adapter(self.active_adapters)

    def reset_lora_parameters(self, adapter_name):
        if adapter_name in self.lora_A.keys():
            nn.init.normal_(self.lora_E[adapter_name], mean=0.0, std=0.02)
            nn.init.normal_(self.lora_A[adapter_name], mean=0.0, std=0.02)
            nn.init.normal_(self.lora_B[adapter_name], mean=0.0, std=0.02)


class SVDLinear(nn.Module, AdaLoraLayer):
    # SVD-based adaptation by a dense layer
    def __init__(
        self,
        base_layer: nn.Module,
        adapter_name: str,
        r: int = 0,
        lora_alpha: int = 1,
        lora_dropout: float = 0.0,
        fan_in_fan_out: bool = False,
        init_lora_weights: bool = True,
        **kwargs,
    ) -> None:
        super().__init__()
        AdaLoraLayer.__init__(self, base_layer)
        # Freezing the pre-trained weight matrix
        self.get_base_layer().weight.requires_grad = False

        self.fan_in_fan_out = fan_in_fan_out
        self._active_adapter = adapter_name
        self.update_layer(adapter_name, r, lora_alpha, lora_dropout, init_lora_weights, **kwargs)

    def merge(self, safe_merge: bool = False, adapter_names: Optional[List[str]] = None) -> None:
        """
        Merge the active adapter weights into the base weights

        Args:
            safe_merge (`bool`, *optional*):
                If True, the merge operation will be performed in a copy of the original weights and check for NaNs
                before merging the weights. This is useful if you want to check if the merge operation will produce
                NaNs. Defaults to `False`.
            adapter_names (`List[str]`, *optional*):
                The list of adapter names that should be merged. If None, all active adapters will be merged. Defaults
                to `None`.
        """
        adapter_names = check_adapters_to_merge(self, adapter_names)
        if not adapter_names:
            # no adapter to merge
            return

        for active_adapter in adapter_names:
            base_layer = self.get_base_layer()
            if active_adapter in self.lora_A.keys():
                if safe_merge:
                    # Note that safe_merge will be slower than the normal merge
                    # because of the copy operation.
                    orig_weights = base_layer.weight.data.clone()
                    orig_weights += self.get_delta_weight(active_adapter)

                    if not torch.isfinite(orig_weights).all():
                        raise ValueError(
                            f"NaNs detected in the merged weights. The adapter {active_adapter} seems to be broken"
                        )

                    base_layer.weight.data = orig_weights
                else:
                    base_layer.weight.data += self.get_delta_weight(active_adapter)
                self.merged_adapters.append(active_adapter)

    def unmerge(self) -> None:
        """
        This method unmerges all merged adapter layers from the base weights.
        """
        if not self.merged:
            warnings.warn("Already unmerged. Nothing to do.")
            return
        while len(self.merged_adapters) > 0:
            active_adapter = self.merged_adapters.pop()
            if active_adapter in self.lora_A.keys():
                self.get_base_layer().weight.data -= self.get_delta_weight(active_adapter)

    def get_delta_weight(self, adapter) -> torch.Tensor:
        return (
            transpose(self.lora_B[adapter] @ (self.lora_A[adapter] * self.lora_E[adapter]), self.fan_in_fan_out)
            * self.scaling[adapter]
            / (self.ranknum[adapter] + 1e-5)
        )

    def forward(self, x: torch.Tensor, *args: Any, **kwargs: Any) -> torch.Tensor:
        if self.disable_adapters:
            if self.merged:
                self.unmerge()
            result = self.base_layer(x, *args, **kwargs)
        elif self.merged:
            result = self.base_layer(x, *args, **kwargs)
        else:
            result = self.base_layer(x, *args, **kwargs)
            for active_adapter in self.active_adapters:
                if active_adapter not in self.lora_A.keys():
                    continue
                lora_A = self.lora_A[active_adapter]
                lora_B = self.lora_B[active_adapter]
                lora_E = self.lora_E[active_adapter]
                dropout = self.lora_dropout[active_adapter]
                scaling = self.scaling[active_adapter]
                ranknum = self.ranknum[active_adapter] + 1e-5

                x = x.to(lora_A.dtype)
                adalora = (lora_A * lora_E).T @ lora_B.T
                # print(self.in_features, self.out_features, adalora.shape, self.target_name)
                # print(self.in_features, self.out_features, adalora.shape, self.target_name, lora_A.shape, lora_B.shape)
                residual = torch.zeros([self.in_features, self.out_features]).type_as(lora_A).to(lora_A.device)
                # print(residual[self.indices_mn[:, 1].long(), self.indices_mn[:, 0].long()].shape)
                # print(residual.shape, x.shape, self.indices_mn.shape, torch.isnan(self.indices_mn).any())
                # print(self.indices_mn[:, 1].long().max(), self.indices_mn[:, 1].long().min(), self.indices_mn[:, 0].long().max(), self.indices_mn[:, 0].long().min())
                residual[self.indices_mn[:, 1].long(), self.indices_mn[:, 0].long()] = adalora.view(-1)
                result += (dropout(x) @ residual) * scaling / ranknum

        return result

    def __repr__(self) -> str:
        rep = super().__repr__()
        return "adalora." + rep


class RankAllocator:
    """
    The RankAllocator for AdaLoraModel. Paper: https://openreview.net/pdf?id=lq62uWRJjiY

    Args:
        config ([`AdaLoraConfig`]): The configuration of the AdaLora model.
        model: the model that we apply AdaLoRA to.

    """

    def __init__(self, model, peft_config, adapter_name):
        self.peft_config = peft_config
        self.adapter_name = adapter_name
        self.beta1 = peft_config.beta1
        self.beta2 = peft_config.beta2
        assert self.beta1 > 0 and self.beta1 < 1
        assert self.beta2 > 0 and self.beta2 < 1

        self.reset_ipt()
        self._set_budget_scheduler(model)

    def set_total_step(self, total_step):
        self.peft_config.total_step = total_step

    def reset_ipt(self):
        self.ipt = {}
        self.exp_avg_ipt = {}
        self.exp_avg_unc = {}

    def _set_budget_scheduler(self, model):
        self.init_bgt = 0
        self.name_set = set()
        for n, p in model.named_parameters():
            if f"lora_A.{self.adapter_name}" in n:
                self.init_bgt += p.size(0)
                self.name_set.add(n.replace("lora_A", "%s"))
        self.name_set = sorted(self.name_set)
        # The total final rank budget
        self.target_bgt = self.peft_config.target_r * len(self.name_set)

    def budget_schedule(self, step: int):
        tinit = self.peft_config.tinit
        tfinal = self.peft_config.tfinal
        total_step = self.peft_config.total_step
        # Initial warmup
        if step <= tinit:
            budget = self.init_bgt
            mask_ind = False
        # Final fine-tuning
        elif step > total_step - tfinal:
            budget = self.target_bgt
            mask_ind = True
        else:
            # Budget decreasing with a cubic scheduler
            mul_coeff = 1 - (step - tinit) / (total_step - tfinal - tinit)
            budget = int((self.init_bgt - self.target_bgt) * (mul_coeff**3) + self.target_bgt)
            mask_ind = True if step % self.peft_config.deltaT == 0 else False
        return budget, mask_ind

    def update_ipt(self, model):
        # Update the sensitivity and uncertainty for every weight
        for n, p in model.named_parameters():
            if "lora_" in n and self.adapter_name in n:
                if n not in self.ipt:
                    self.ipt[n] = torch.zeros_like(p)
                    self.exp_avg_ipt[n] = torch.zeros_like(p)
                    self.exp_avg_unc[n] = torch.zeros_like(p)
                with torch.no_grad():
                    self.ipt[n] = (p * p.grad).abs().detach()
                    # Sensitivity smoothing
                    self.exp_avg_ipt[n] = self.beta1 * self.exp_avg_ipt[n] + (1 - self.beta1) * self.ipt[n]
                    # Uncertainty quantification
                    self.exp_avg_unc[n] = (
                        self.beta2 * self.exp_avg_unc[n] + (1 - self.beta2) * (self.ipt[n] - self.exp_avg_ipt[n]).abs()
                    )

    def _element_score(self, n):
        return self.exp_avg_ipt[n] * self.exp_avg_unc[n]

    def _combine_ipt(self, ipt_E, ipt_AB):
        ipt_AB = ipt_AB.sum(dim=1, keepdim=False)
        sum_ipt = ipt_E.view(-1) + ipt_AB.view(-1)
        return sum_ipt

    def mask_to_budget(self, model, budget):
        value_ipt = {}
        vector_ipt = {}
        triplet_ipt = {}
        # Get the importance score for A, E, B
        for n, p in model.named_parameters():
            if f"lora_A.{self.adapter_name}" in n:
                entry_ipt = self._element_score(n)
                comb_ipt = torch.mean(entry_ipt, dim=1, keepdim=True)
                name_m = n.replace("lora_A", "%s")
                if name_m not in vector_ipt:
                    vector_ipt[name_m] = [comb_ipt]
                else:
                    vector_ipt[name_m].append(comb_ipt)
            if f"lora_B.{self.adapter_name}" in n:
                entry_ipt = self._element_score(n)
                comb_ipt = torch.mean(entry_ipt, dim=0, keepdim=False).view(-1, 1)
                name_m = n.replace("lora_B", "%s")
                if name_m not in vector_ipt:
                    vector_ipt[name_m] = [comb_ipt]
                else:
                    vector_ipt[name_m].append(comb_ipt)
            if f"lora_E.{self.adapter_name}" in n:
                entry_ipt = self._element_score(n)
                name_m = n.replace("lora_E", "%s")
                value_ipt[name_m] = entry_ipt

        all_score = []
        # Calculate the score for each triplet
        for name_m in vector_ipt:
            ipt_E = value_ipt[name_m]
            ipt_AB = torch.cat(vector_ipt[name_m], dim=1)
            sum_ipt = self._combine_ipt(ipt_E, ipt_AB)
            name_E = name_m % "lora_E"
            triplet_ipt[name_E] = sum_ipt.view(-1, 1)
            all_score.append(sum_ipt.view(-1))

        # Get the threshold by ranking ipt
        mask_threshold = torch.kthvalue(
            torch.cat(all_score),
            k=self.init_bgt - budget,
        )[0].item()

        rank_pattern = {}
        # Mask the unimportant triplets
        with torch.no_grad():
            for n, p in model.named_parameters():
                if f"lora_E.{self.adapter_name}" in n:
                    p.masked_fill_(triplet_ipt[n] <= mask_threshold, 0.0)
                    rank_pattern[n] = (~(triplet_ipt[n] <= mask_threshold)).view(-1).tolist()
        return rank_pattern

    def update_and_allocate(self, model, global_step, force_mask=False):
        # # Update the importance score and allocate the budget
        if global_step < self.peft_config.total_step - self.peft_config.tfinal:
            self.update_ipt(model)
        budget, mask_ind = self.budget_schedule(global_step)
        # Allocate the budget according to importance scores
        if mask_ind or force_mask:
            rank_pattern = self.mask_to_budget(model, budget)
        else:
            rank_pattern = None
        return budget, rank_pattern

    def mask_using_rank_pattern(self, model, rank_pattern):
        # Mask the unimportant triplets
        is_adapter_name_truncated = False
        if self.adapter_name not in next(iter(rank_pattern.keys())):
            is_adapter_name_truncated = True

        with torch.no_grad():
            for n, p in model.named_parameters():
                if f"lora_E.{self.adapter_name}" in n:
                    key = n if not is_adapter_name_truncated else n.replace(f".{self.adapter_name}", "")
                    mask = torch.Tensor(rank_pattern[key]).unsqueeze(-1).to(p.device)
                    p.masked_fill_(~mask.bool(), 0.0)
