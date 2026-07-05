"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

import {
  ConditionTree,
  ConditionItem,
  ConditionGroup,
} from "../types/device-selector";

interface LogicalTreeModalProps {
  isOpen: boolean
  onClose: () => void
  conditionTree: ConditionTree
}

// Helper to generate ASCII tree
const generateTreeVisualization = (conditionTree: ConditionTree): string => {
  const lines: string[] = []

  // Add header
  lines.push(`ROOT (${conditionTree.internalLogic})`)

  if (conditionTree.items.length === 0) {
    lines.push('  (empty)')
    return lines.join('\n')
  }

  const renderTreeItemText = (
    item: ConditionItem | ConditionGroup,
    prefix: string = '',
    isLast: boolean = true,
    isFirst: boolean = false
  ) => {
    const connector = isLast ? '└─ ' : '├─ '
    const extension = isLast ? '   ' : '│  '

    if ('type' in item && item.type === 'group') {
      const group = item as ConditionGroup

      // Add logic operator badge if not first
      const logicBadge = !isFirst ? `[${group.logic}] ` : ''
      lines.push(`${prefix}${connector}${logicBadge}GROUP (${group.internalLogic})`)

      // Render group items
      if (group.items.length === 0) {
        lines.push(`${prefix}${extension}   (empty group)`)
      } else {
        group.items.forEach((subItem, subIndex) => {
          const subIsLast = subIndex === group.items.length - 1
          renderTreeItemText(
            subItem,
            `${prefix}${extension}`,
            subIsLast,
            subIndex === 0
          )
        })
      }
    } else {
      // This is a condition
      const condition = item as ConditionItem
      lines.push(
        `${prefix}${connector}${condition.field} ${condition.operator} "${condition.value}"`
      )
    }
  }

  // Render all root-level items
  conditionTree.items.forEach((item, index) => {
    const isLast = index === conditionTree.items.length - 1
    renderTreeItemText(item, '', isLast, index === 0)
  })

  return lines.join('\n')
}

export function LogicalTreeModal({
  isOpen,
  onClose,
  conditionTree,
}: LogicalTreeModalProps) {
  const treeVisualization = generateTreeVisualization(conditionTree)

  return (
    <Dialog open={isOpen} onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Logical Tree Structure</DialogTitle>
          <DialogDescription>
            Visual representation of how conditions are nested and combined.
          </DialogDescription>
        </DialogHeader>
        <div className="bg-slate-900 text-slate-50 p-4 rounded-md overflow-x-auto font-mono text-sm whitespace-pre">
          {treeVisualization}
        </div>
        <div className="flex justify-end">
          <Button onClick={onClose}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
