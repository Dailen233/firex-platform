/**
 * Province-level aggregation of publicly described grid operating regions.
 * This is an illustrative grouping, not a verified dispatch-boundary dataset.
 */
export interface GridRegion {
  id: string
  name: string
  shortName: string
  operator: string
  provinceCodes: string[]
  color: string
}

export const gridRegions: GridRegion[] = [
  { id: 'north', name: '华北电网', shortName: '华北', operator: '国家电网', provinceCodes: ['110000', '120000', '130000', '140000', '370000'], color: '#287a68' },
  { id: 'east', name: '华东电网', shortName: '华东', operator: '国家电网', provinceCodes: ['310000', '320000', '330000', '340000', '350000'], color: '#3b6e9a' },
  { id: 'central', name: '华中电网', shortName: '华中', operator: '国家电网', provinceCodes: ['360000', '410000', '420000', '430000'], color: '#8162a2' },
  { id: 'northeast', name: '东北电网', shortName: '东北', operator: '国家电网', provinceCodes: ['210000', '220000', '230000'], color: '#a45d4e' },
  { id: 'northwest', name: '西北电网', shortName: '西北', operator: '国家电网', provinceCodes: ['610000', '620000', '630000', '640000', '650000'], color: '#9a7a38' },
  { id: 'southwest', name: '西南电网', shortName: '西南', operator: '国家电网', provinceCodes: ['500000', '510000', '540000'], color: '#387e7a' },
  { id: 'southern', name: '中国南方电网', shortName: '南方电网', operator: '中国南方电网', provinceCodes: ['440000', '450000', '460000', '520000', '530000'], color: '#527d47' },
]

export const gridUnassigned = {
  id: 'unassigned',
  name: '暂未纳入 / 待核定',
  shortName: '待核定',
  provinceCodes: ['150000'],
  color: '#5b6671',
}

export function gridRegionForProvince(code: string | undefined): GridRegion | typeof gridUnassigned | undefined {
  if (!code) return undefined
  return gridRegions.find(region => region.provinceCodes.includes(code))
    ?? (gridUnassigned.provinceCodes.includes(code) ? gridUnassigned : undefined)
}

export function provinceCodesForGridRegion(id: string): string[] {
  return [...gridRegions, gridUnassigned].find(region => region.id === id)?.provinceCodes ?? []
}

export const gridRegionSources = [
  { label: '国家电网区域电网与跨区联网介绍', url: 'https://www.nc.sgcc.com.cn/zxzx/zbdt/2024/12/468382.shtml' },
  { label: '南方电网经营区域', url: 'https://cxwt.sc.csg.cn/about.jhtml' },
  { label: '国家发展改革委：电力调度分级管理规定', url: 'https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=19964' },
  { label: '国家电网区域分部范围公开文件', url: 'https://static.cninfo.com.cn/finalpage/2026-03-04/1224995610.PDF' },
]
