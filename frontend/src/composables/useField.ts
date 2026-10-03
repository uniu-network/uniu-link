import type { ComputedRef, InjectionKey } from 'vue'
export const fieldLabelKey: InjectionKey<ComputedRef<string>> = Symbol('field-label')
export const formBusyKey: InjectionKey<ComputedRef<boolean>> = Symbol('form-busy')
