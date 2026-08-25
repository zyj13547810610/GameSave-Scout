<script setup lang="ts">
import type { EngineSaveRuleDraft, GameSaveRuleDraft, RuleDraft, SaveRuleLocationDraft } from '../../api/contracts'
import RuleLocationEditor from './RuleLocationEditor.vue'

type SaveDraft = GameSaveRuleDraft | EngineSaveRuleDraft
const props = defineProps<{ modelValue: SaveDraft; readonly: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: SaveDraft] }>()

function update(patch: Partial<RuleDraft>) {
  emit('update:modelValue', { ...props.modelValue, ...patch } as SaveDraft)
}

function valuesFor(key: 'titles' | 'product_ids' | 'engine_ids'): string[] {
  if (key === 'engine_ids') return props.modelValue.type === 'save_engine' ? props.modelValue.engine_ids : []
  return props.modelValue.type === 'save_game' ? props.modelValue[key] : []
}

function updateValues(key: 'titles' | 'product_ids' | 'engine_ids', values: string[]) {
  update({ [key]: values })
}

function updateValue(key: 'titles' | 'product_ids' | 'engine_ids', index: number, value: string) {
  updateValues(key, valuesFor(key).map((item, itemIndex) => itemIndex === index ? value : item))
}

function addValue(key: 'titles' | 'product_ids' | 'engine_ids') {
  if (valuesFor(key).length >= 64) return
  updateValues(key, [...valuesFor(key), ''])
}

function removeValue(key: 'titles' | 'product_ids' | 'engine_ids', index: number) {
  updateValues(key, valuesFor(key).filter((_, itemIndex) => itemIndex !== index))
}

function updateLocation(index: number, value: SaveRuleLocationDraft) {
  update({ locations: props.modelValue.locations.map((item, itemIndex) => itemIndex === index ? value : item) })
}

function addLocation() {
  if (props.modelValue.locations.length >= 32) return
  update({
    locations: [
      ...props.modelValue.locations,
      {
        kind: 'directory', path: '<winDocuments>', category: 'save',
        confidence: .8, require_existing: false,
      },
    ],
  })
}

function removeLocation(index: number) {
  update({ locations: props.modelValue.locations.filter((_, itemIndex) => itemIndex !== index) })
}

function moveLocation(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= props.modelValue.locations.length) return
  const next = [...props.modelValue.locations]
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  update({ locations: next })
}
</script>

<template>
  <section class="rule-type-form">
    <fieldset v-if="modelValue.type === 'save_game'" data-test="game-title-selectors" class="rule-editor-group">
      <legend>精确标题与别名（至少一项）</legend>
      <div v-for="(value, index) in modelValue.titles" :key="index" class="rule-inline-row">
        <input :disabled="readonly" :value="value" @input="updateValue('titles', index, ($event.target as HTMLInputElement).value)">
        <button v-if="!readonly" class="danger" type="button" @click="removeValue('titles', index)">删除</button>
      </div>
      <button v-if="!readonly" class="secondary" type="button" :disabled="modelValue.titles.length >= 64" @click="addValue('titles')">添加标题/别名</button>
      <p v-if="modelValue.titles.length === 0" class="inline-error">游戏专属存档规则至少需要一个精确标题或别名。</p>
    </fieldset>
    <fieldset v-if="modelValue.type === 'save_game'" data-test="product-id-selectors" class="rule-editor-group">
      <legend>产品编号（可选）</legend>
      <p class="rule-field-help" data-test="product-id-help">
        支持 steam、gog、epic、itch、vndb、dlsite；格式为“平台:编号”，每项填写一个，没有可留空。
      </p>
      <div v-for="(value, index) in modelValue.product_ids" :key="index" class="rule-inline-row">
        <input :disabled="readonly" :value="value" placeholder="例如 vndb:v123" @input="updateValue('product_ids', index, ($event.target as HTMLInputElement).value)">
        <button v-if="!readonly" class="danger" type="button" @click="removeValue('product_ids', index)">删除</button>
      </div>
      <button v-if="!readonly" class="secondary" type="button" :disabled="modelValue.product_ids.length >= 64" @click="addValue('product_ids')">添加产品编号</button>
    </fieldset>
    <fieldset v-if="modelValue.type === 'save_engine'" data-test="engine-id-selectors" class="rule-editor-group">
      <legend>稳定引擎 ID（至少一项）</legend>
      <div v-for="(value, index) in modelValue.engine_ids" :key="index" class="rule-inline-row">
        <input :disabled="readonly" :value="value" placeholder="例如 unity" @input="updateValue('engine_ids', index, ($event.target as HTMLInputElement).value)">
        <button v-if="!readonly" class="danger" type="button" @click="removeValue('engine_ids', index)">删除</button>
      </div>
      <button v-if="!readonly" class="secondary" type="button" :disabled="modelValue.engine_ids.length >= 64" @click="addValue('engine_ids')">添加引擎 ID</button>
      <p v-if="modelValue.engine_ids.length === 0" class="inline-error">引擎通用存档规则至少需要一个稳定引擎 ID。</p>
    </fieldset>

    <fieldset class="rule-editor-group">
      <legend>存档位置（最多 32 项）</legend>
      <RuleLocationEditor
        v-for="(location, index) in modelValue.locations"
        :key="index"
        :model-value="location"
        :readonly="readonly"
        :index="index"
        @update:model-value="updateLocation(index, $event)"
        @remove="removeLocation(index)"
        @up="moveLocation(index, -1)"
        @down="moveLocation(index, 1)"
      />
      <button v-if="!readonly" class="secondary" type="button" :disabled="modelValue.locations.length >= 32" @click="addLocation">添加位置</button>
      <p v-if="modelValue.locations.length === 0" class="inline-error">至少添加一个存档位置。</p>
    </fieldset>
  </section>
</template>
