/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Lane ID Tag for Per-Lane DCQCN ECMP routing
 */

#include "lane-id-tag.h"

namespace ns3 {

NS_OBJECT_ENSURE_REGISTERED(LaneIdTag);

LaneIdTag::LaneIdTag()
    : Tag(),
      m_laneId(0)
{
}

LaneIdTag::LaneIdTag(uint32_t laneId)
    : Tag(),
      m_laneId(laneId)
{
}

TypeId
LaneIdTag::GetTypeId(void)
{
    static TypeId tid = TypeId("ns3::LaneIdTag")
        .SetParent<Tag>()
        .AddConstructor<LaneIdTag>()
        ;
    return tid;
}

TypeId
LaneIdTag::GetInstanceTypeId(void) const
{
    return GetTypeId();
}

uint32_t
LaneIdTag::GetSerializedSize(void) const
{
    return sizeof(m_laneId);
}

void
LaneIdTag::Serialize(TagBuffer i) const
{
    i.WriteU32(m_laneId);
}

void
LaneIdTag::Deserialize(TagBuffer i)
{
    m_laneId = i.ReadU32();
}

void
LaneIdTag::SetLaneId(uint32_t laneId)
{
    m_laneId = laneId;
}

uint32_t
LaneIdTag::GetLaneId(void) const
{
    return m_laneId;
}

void
LaneIdTag::Print(std::ostream &os) const
{
    os << "LaneId=" << m_laneId;
}

} // namespace ns3
