/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Lane ID Tag for Per-Lane DCQCN ECMP routing
 */

#ifndef LANE_ID_TAG_H
#define LANE_ID_TAG_H

#include "ns3/tag.h"

namespace ns3 {

/**
 * \brief Tag to carry Lane ID for per-lane ECMP routing
 *
 * This tag is attached to packets in per-lane DCQCN mode to enable
 * consistent routing for all flows within the same lane.
 */
class LaneIdTag : public Tag
{
public:
    LaneIdTag();
    LaneIdTag(uint32_t laneId);

    static TypeId GetTypeId(void);
    virtual TypeId GetInstanceTypeId(void) const;
    virtual void Print(std::ostream &os) const;
    virtual uint32_t GetSerializedSize(void) const;
    virtual void Serialize(TagBuffer i) const;
    virtual void Deserialize(TagBuffer i);

    void SetLaneId(uint32_t laneId);
    uint32_t GetLaneId(void) const;

private:
    uint32_t m_laneId;
};

} // namespace ns3

#endif /* LANE_ID_TAG_H */
