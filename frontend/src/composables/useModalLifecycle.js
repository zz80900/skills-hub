import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

function findFirstFocusableElement(root) {
  if (!root) {
    return null
  }
  const selectors = [
    'button:not([disabled])',
    '[href]',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ]
  const elements = root.querySelectorAll(selectors.join(','))
  return Array.from(elements).find((element) => element instanceof HTMLElement) || null
}

export function useModalLifecycle(openSource, close) {
  const dialogRef = ref(null)
  let lastActiveElement = null

  function restoreFocus() {
    if (lastActiveElement instanceof HTMLElement && document.contains(lastActiveElement)) {
      lastActiveElement.focus({ preventScroll: true })
    }
    lastActiveElement = null
  }

  function handleKeydown(event) {
    if (event.key === 'Escape') {
      close()
    }
  }

  function handleBackdropClick(event) {
    if (event.target === event.currentTarget) {
      close()
    }
  }

  async function focusDialog() {
    await nextTick()
    const dialog = dialogRef.value
    if (!dialog) {
      return
    }
    const focusTarget = findFirstFocusableElement(dialog) || dialog
    focusTarget.focus({ preventScroll: true })
  }

  watch(
    openSource,
    (open) => {
      if (open) {
        lastActiveElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
        window.addEventListener('keydown', handleKeydown)
        document.body.style.overflow = 'hidden'
        focusDialog()
        return
      }
      window.removeEventListener('keydown', handleKeydown)
      document.body.style.overflow = ''
      restoreFocus()
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', handleKeydown)
    document.body.style.overflow = ''
    restoreFocus()
  })

  return {
    dialogRef,
    handleBackdropClick,
  }
}
