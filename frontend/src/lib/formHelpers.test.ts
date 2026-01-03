import { describe, expect, it } from 'vitest'
import {
  getCheckboxValue,
  getFormFieldValue,
  getFormValues,
  getInputNumber,
  getSelectValue,
  getSelectValueOptional,
  getSelectValueRaw,
  getTextareaValue,
} from '@/lib/formHelpers'

describe('formHelpers', () => {
  it('getSelectValue validates and falls back', () => {
    const validator = (v: string): v is 'a' | 'b' => v === 'a' || v === 'b'
    const event = { target: { value: 'a' } } as any
    expect(getSelectValue(event, validator, 'b')).toBe('a')

    const bad = { target: { value: 'x' } } as any
    expect(getSelectValue(bad, validator, 'b')).toBe('b')
  })

  it('getSelectValueOptional returns undefined for invalid', () => {
    const validator = (v: string): v is 'a' | 'b' => v === 'a' || v === 'b'
    expect(getSelectValueOptional({ target: { value: 'x' } } as any, validator)).toBeUndefined()
  })

  it('getSelectValueRaw returns string', () => {
    expect(getSelectValueRaw({ target: { value: 'x' } } as any)).toBe('x')
  })

  it('getInputNumber parses numeric values with fallback', () => {
    expect(getInputNumber({ target: { value: '10' } } as any)).toBe(10)
    expect(getInputNumber({ target: { value: 'nope' } } as any, 5)).toBe(5)
  })

  it('getCheckboxValue returns checked boolean', () => {
    expect(getCheckboxValue({ target: { checked: true } } as any)).toBe(true)
  })

  it('getTextareaValue returns textarea string', () => {
    expect(getTextareaValue({ target: { value: 'hi' } } as any)).toBe('hi')
  })

  it('getFormValues and getFormFieldValue extract FormData strings', () => {
    const form = document.createElement('form')
    const inputA = document.createElement('input')
    inputA.name = 'a'
    inputA.value = '1'
    form.appendChild(inputA)

    const inputB = document.createElement('input')
    inputB.name = 'b'
    inputB.value = '2'
    form.appendChild(inputB)

    expect(getFormValues(form)).toEqual({ a: '1', b: '2' })
    expect(getFormFieldValue(form, 'a')).toBe('1')
    expect(getFormFieldValue(form, 'missing')).toBeNull()
  })
})

