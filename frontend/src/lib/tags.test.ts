// Step 27: the "[C]" token parser (contracts §2.5) and the picker's insert helper.
import { describe, expect, it } from 'vitest'
import { sanJoseV1, sanJoseV2 } from '@/fixtures'
import { dayColor, DAY_COLORS, firstDayByTag, insertTag, isTag, parseTagTokens, tagsToLinks } from './tags'

const tag = (t: string) => ({ kind: 'tag', tag: t })
const text = (t: string) => ({ kind: 'text', text: t })

describe('parseTagTokens', () => {
  it('turns a single-letter tag into a tag segment, keeping the text around it', () => {
    expect(parseTagTokens('replace [F] please')).toEqual([text('replace '), tag('F'), text(' please')])
  })

  it('handles two-letter tags', () => {
    expect(parseTagTokens('swap [AA] and [ZZ]')).toEqual([text('swap '), tag('AA'), text(' and '), tag('ZZ')])
  })

  it('splits adjacent tags with no text between them', () => {
    expect(parseTagTokens('[A][B][AB]')).toEqual([tag('A'), tag('B'), tag('AB')])
  })

  it('handles a tag at the very start and the very end', () => {
    expect(parseTagTokens('[C] then [D]')).toEqual([tag('C'), text(' then '), tag('D')])
  })

  it('ignores [abc], lowercase, three-letter and non-letter brackets', () => {
    for (const s of ['see [abc]', 'see [a]', 'see [Ab]', 'see [ABC]', 'see [1]', 'see []', 'see [ A ]']) {
      expect(parseTagTokens(s)).toEqual([text(s)])
    }
  })

  it('ignores markdown links, even when the link text looks like a tag', () => {
    const s = 'book [A](https://example.com) or [here](https://x.y)'
    expect(parseTagTokens(s)).toEqual([text(s)])
  })

  it('still finds a tag followed by a space and a parenthesis', () => {
    expect(parseTagTokens('[F] (Baconhouse)')).toEqual([tag('F'), text(' (Baconhouse)')])
  })

  it('returns plain text unchanged and an empty string as no segments', () => {
    expect(parseTagTokens('no tags here')).toEqual([text('no tags here')])
    expect(parseTagTokens('')).toEqual([])
  })
})

describe('tagsToLinks', () => {
  it('turns every tag token into a #tag link and leaves other text and links alone', () => {
    expect(tagsToLinks('[A][B] see [abc] and [C](http://x)')).toBe(
      '[A](#tag-A)[B](#tag-B) see [abc] and [C](http://x)',
    )
  })
})

describe('isTag', () => {
  it('accepts one or two uppercase letters only', () => {
    expect(isTag('C')).toBe(true)
    expect(isTag('AA')).toBe(true)
    for (const s of ['', 'c', 'ABC', '[C]', 'C ', '1']) expect(isTag(s)).toBe(false)
  })
})

describe('insertTag', () => {
  it('inserts "[C] " at the cursor in the middle of the text', () => {
    // cursor after "replace " (index 8)
    expect(insertTag('replace with a park', 8, 8, 'C')).toEqual({ text: 'replace [C] with a park', cursor: 12 })
  })

  it('adds a space before the tag when the cursor is right after a word', () => {
    expect(insertTag('replace', 7, 7, 'H')).toEqual({ text: 'replace [H] ', cursor: 12 })
  })

  it('inserts at the start of the text without a leading space', () => {
    expect(insertTag('is too far', 0, 0, 'G')).toEqual({ text: '[G] is too far', cursor: 4 })
  })

  it('works on empty text', () => {
    expect(insertTag('', 0, 0, 'AA')).toEqual({ text: '[AA] ', cursor: 5 })
  })

  it('replaces the selected text', () => {
    // "XX" selected at [8, 10)
    expect(insertTag('replace XX now', 8, 10, 'L')).toEqual({ text: 'replace [L]  now', cursor: 12 })
  })
})

describe('day colors', () => {
  it('cycles through the palette by day number', () => {
    expect(dayColor(1)).toBe(DAY_COLORS[0])
    expect(dayColor(2)).toBe(DAY_COLORS[1])
    expect(dayColor(DAY_COLORS.length + 1)).toBe(DAY_COLORS[0])
  })

  it('maps each tag to the first day it appears on', () => {
    const first = firstDayByTag(sanJoseV2)
    expect(first.get('A')).toBe(1)
    expect(first.get('L')).toBe(2)
    // C (the airport) is on day 1 and again on the last day: it keeps day 1.
    expect(first.get('C')).toBe(1)
    expect(firstDayByTag(null).size).toBe(0)
    expect(firstDayByTag(sanJoseV1).has('F')).toBe(true)
  })
})
