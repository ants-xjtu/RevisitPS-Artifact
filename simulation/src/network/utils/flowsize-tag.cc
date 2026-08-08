/* Modification */
/*
 * flowsize-tag.cc
 *
 */

 #include "flowsize-tag.h"

 namespace ns3
 {
 
 TypeId
 FlowsizeTag::GetTypeId(void)
 {
     static TypeId tid = TypeId("ns3::FlowsizeTag")
                             .SetParent<Tag>()
                             .AddConstructor<FlowsizeTag>();
     return tid;
 }
 
 TypeId
 FlowsizeTag::GetInstanceTypeId(void) const
 {
     return GetTypeId();
 }
 
 uint32_t
 FlowsizeTag::GetSerializedSize(void) const
 {
     return 4;
 }
 
 void
 FlowsizeTag::Serialize(TagBuffer i) const
 {
     i.WriteU32(m_value);
 }
 
 void
 FlowsizeTag::Deserialize(TagBuffer i)
 {
     m_value = i.ReadU32();
 }
 
 void
 FlowsizeTag::Print(std::ostream& os) const
 {
     os << "v=" << (uint32_t)m_value;
 }
 
 void
 FlowsizeTag::SetValue(uint32_t value)
 {
     m_value = value;
 }
 
 uint32_t
 FlowsizeTag::GetValue(void) const
 {
     return m_value;
 }
 
 /* Modification */
 
 } // namespace ns3
 